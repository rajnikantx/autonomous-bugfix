import json
import time
from enum import Enum
from typing import Literal, Optional, Dict, Any, Tuple, List

from loguru import logger
from openai import OpenAI
from pydantic import BaseModel, Field
from datetime import datetime
from dataclasses import dataclass, field

from src.config import settings
from src.tools.file_ops import read_file
from src.tools.code_search import (
    extract_snippet,
    grep_codebase,
    get_function_definition,
    get_class_definition,
    get_function_callers,
    get_functions_of_file,
    get_imports_of_file,
)

MAX_ITERATIONS = 10
MAX_RETRIES = 3


INVESTIGATOR_REACT_PROMPT = """
    You are the Investigator agent in an autonomous bug-fixing system.

    A test suite failed. You have been handed one failing test, its traceback, and read-only tools to explore the codebase. Your job is to find the root cause -- the actual mechanism that causes the failure, not just the symptom -- and gather enough concrete evidence that a separate Fixer agent can write a correct patch from your findings alone, without re-investigating from scratch. You do not write or suggest the fix yourself; that is out of scope for this role.

    ## Tools
    - extract_snippet(file_path, line_no, radius=10) -- your default first move on any file. Centers on a line (e.g. the crash line from the traceback) and shows the lines around it, with the target line marked >>>. Cheaper and more focused than read_file.
    - read_file(file_path) -- full file contents. Use for short files, or once you already know you need the whole picture.
    - grep_codebase(pattern, sandbox_path, file_extension=".py") -- regex/text search across the sandbox. Use when you're looking for a usage, constant, config flag, or error string and don't yet have an exact location.
    - get_function_definition(function_name, sandbox_path) / get_class_definition(class_name, sandbox_path) -- AST-exact complete source, including decorators. Prefer these over grep once you know a name -- they never truncate or miss a decorator the way a text search can.
    - get_function_callers(function_name, sandbox_path) -- every call site of a function via AST, no false positives from comments or strings. Use before concluding a fix approach: a change that looks correct in isolation can still break a caller that relies on the current behavior.
    - get_functions_of_file(file_path) / get_imports_of_file(file_path) -- structural overview of a file. Use when you're not sure you're even in the right file, or suspect an import-time issue (circular import, wrong symbol, shadowed name).

    ## Method
    1. Start from the traceback: find the exact file and line where the exception was actually raised, and extract_snippet it first.
    2. Read outward: pull the complete function or class the crash happened in, so you're reasoning about real code, not a fragment.
    3. Form a hypothesis, then look for evidence that would confirm or rule it out. Every tool call should test something specific -- don't gather code just because it's nearby.
    4. Before you conclude, check get_function_callers on anything you're about to point to as needing a change, so the eventual patch doesn't just relocate the bug or break a caller.
    5. If the evidence points away from the code you're currently reading -- bad input, a wrong function being called, an import shadowing issue -- follow it with grep_codebase or get_imports_of_file rather than assuming.

    ## When to stop
    Stop calling tools as soon as you can state the root cause and name the exact file(s), line(s), function(s), or class(es) responsible, with the evidence for each. You have {max_iterations} turns -- treat that as a budget, not a target. Never call the same tool with the same arguments twice, and don't keep exploring once another tool call wouldn't change your conclusion.

    ## Rules
    - Never state a file path, line number, or function name you didn't actually get back from a tool.
    - If a tool call errors, read the error and adjust -- don't repeat the identical call expecting a different result.
    - If two turns in a row haven't moved you closer to a root cause, say so and change strategy rather than repeating the same kind of call.
    - Describe the bug and the evidence for it, not a proposed fix.

    When you're confident in the root cause, respond in plain language with your conclusion and the evidence for it, and do not call another tool -- that's what tells the system your investigation is complete.
"""

INVESTIGATOR_EXTRACT_PROMPT = """
    You are the extraction stage of the Investigator agent in an autonomous bug-fixing system.

    You will be given the transcript of a completed investigation into one or more failing tests: every reasoning step taken, every tool called, and every result returned. Turn that transcript into structured findings that a separate Fixer agent will use to write a patch without re-reading the codebase itself. This is evidence-to-record extraction, not fresh analysis -- use only what the transcript actually shows, and don't soften language into hedges just to sound careful.

    For each bug the transcript investigated, fill in:
    - bug_id / test_name: reuse exactly the identifiers given to you for this investigation.
    - root_cause: one to two sentences on the mechanism, not the symptom -- e.g. "the retry counter increments before the transient check runs, so non-transient errors still consume a retry" rather than "retries don't work right".
    - affected_files: every file that needs to change to fix the bug -- not every file that was merely read along the way.
    - affected_lines: line numbers per file, taken only from what a tool call in the transcript actually showed.
    - affected_functions / affected_classes: fully qualified names (module.path.Class.method or module.path.function) wherever the transcript makes the full path clear; a bare name only if that's genuinely all the evidence supports.
    - code_snippets: the specific block(s) from the transcript's tool output that show the bug -- not the whole file.
    - file_reasoning: one sentence per affected file on why that file specifically needs to change.
    - confidence:
        - high -- the transcript traced the bug to a specific line or function with a clear causal mechanism, and caller impact was checked where relevant.
        - medium -- the root cause is identified, but caller impact wasn't checked, or the evidence is circumstantial rather than a directly observed line.
        - low -- the investigation hit its iteration limit, a circuit breaker, or repeated tool failures before reaching a confirmed root cause. Say so plainly instead of presenting a guess as settled.
    - reasoning_trace: the actual chain of steps, in your own words, in the order they happened -- enough for a human reviewer to audit how the conclusion was reached without re-reading the raw transcript.

    If the transcript doesn't have enough evidence to support a field, leave it empty rather than inventing something plausible-sounding. If the transcript surfaces more than one distinct bug, return one result per bug.
"""

class FileLines(BaseModel):
    file: str = Field(description="File path")
    lines: list[int] = Field(default_factory=list, description="Line numbers of interest in this file")


class FileSnippet(BaseModel):
    file: str = Field(description="File path")
    snippet: str = Field(description="Relevant code block from this file")


class FileReasoning(BaseModel):
    file: str = Field(description="File path")
    reasoning: str = Field(description="Why this file is linked to the bug")


class InvestigationResult(BaseModel):
    bug_id: str = Field(description="ID of the bug being investigated")
    test_name: str = Field(description="Name of the failing test")
    root_cause: str = Field(description="1-2 sentence explanation of the actual bug")
    affected_files: list[str] = Field(default_factory=list, description="All files that need changing")
    affected_lines: list[FileLines] = Field(
        default_factory=list,
        description="Per-file line numbers of interest"
    )
    affected_functions: list[str] = Field(
        default_factory=list,
        description="Fully qualified function/method names"
    )
    affected_classes: list[str] = Field(
        default_factory=list,
        description="Fully qualified class names"
    )
    code_snippets: list[FileSnippet] = Field(
        default_factory=list,
        description="Per-file relevant code blocks"
    )
    file_reasoning: list[FileReasoning] = Field(
        default_factory=list,
        description="Per-file reasoning for why it's linked to the bug"
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence in the root cause analysis"
    )
    reasoning_trace: list[str] = Field(
        default_factory=list,
        description="Steps the investigator took"
    )


class InvestigationOutput(BaseModel):
    results: list[InvestigationResult] = Field(
        description="The complete list of investigation results for the tracked bugs."
    )


class ActionStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    MAX_RETRIES = "max_retries"


@dataclass
class Step:
    iteration_number: int
    observation: str
    reasoning: str
    action_name: Optional[str] = None
    action_input: Optional[Dict] = None
    result: Optional[str] = None
    status: ActionStatus = ActionStatus.SUCCESS
    timestamp: datetime = field(default_factory=datetime.now)


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "extract_snippet",
            "description": "Read lines around a specific line number. The crash line is marked with >>>. Preferred first tool for examining any file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file inside the sandbox"},
                    "line_no": {"type": "integer", "description": "1-based line number to center on"},
                    "radius": {"type": "integer", "description": "Lines before and after to include (default 10)", "default": 10},
                },
                "required": ["file_path", "line_no"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read full file content with line numbers. Use for small files or when you need the complete picture.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file inside the sandbox"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_codebase",
            "description": "Search for text or regex pattern across all .py files in the sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Text or regex pattern to search for"},
                    "sandbox_path": {"type": "string", "description": "Absolute path to the sandbox root directory"},
                },
                "required": ["pattern", "sandbox_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_function_definition",
            "description": "Get the COMPLETE source of a function using AST parsing. Returns full body including decorators.",
            "parameters": {
                "type": "object",
                "properties": {
                    "function_name": {"type": "string", "description": "Name of the function to find"},
                    "sandbox_path": {"type": "string", "description": "Absolute path to the sandbox root directory"},
                },
                "required": ["function_name", "sandbox_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_class_definition",
            "description": "Get the COMPLETE source of a class with method summary. Use for class-related bugs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_name": {"type": "string", "description": "Name of the class to find"},
                    "sandbox_path": {"type": "string", "description": "Absolute path to the sandbox root directory"},
                },
                "required": ["class_name", "sandbox_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_function_callers",
            "description": "Find ALL call sites of a function using AST. More precise than grep — no false positives from comments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "function_name": {"type": "string", "description": "Name of the function to find callers of"},
                    "sandbox_path": {"type": "string", "description": "Absolute path to the sandbox root directory"},
                },
                "required": ["function_name", "sandbox_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_functions_of_file",
            "description": "Get overview of all functions and classes defined in a file with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file inside the sandbox"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_imports_of_file",
            "description": "Get all import statements from a file with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file inside the sandbox"},
                },
                "required": ["file_path"],
            },
        },
    },
]


TOOL_DISPATCH = {
    "read_file": read_file,
    "extract_snippet": extract_snippet,
    "grep_codebase": grep_codebase,
    "get_function_definition": get_function_definition,
    "get_function_callers": get_function_callers,
    "get_class_definition": get_class_definition,
    "get_functions_of_file": get_functions_of_file,
    "get_imports_of_file": get_imports_of_file,
}


class Investigate:
    def __init__(self):
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.INVESTIGATE_MODEL
        self.max_iterations = MAX_ITERATIONS
        self.max_retries = MAX_RETRIES
        self.step_chain: List[Step] = []
        self._error_counts: Dict[str, int] = {}

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> Tuple[str, ActionStatus]:
        tool_func = TOOL_DISPATCH.get(name)
        if not tool_func:
            return f"Error: Unknown tool '{name}'", ActionStatus.ERROR

        try:
            result = tool_func(**args)
            return str(result), ActionStatus.SUCCESS
        except Exception as e:
            return f"Error executing {name}: {str(e)}", ActionStatus.ERROR

    def _execute_with_retry(self, name: str, args: Dict, attempt: int = 1) -> Tuple[str, ActionStatus]:
        result, status = self._execute_tool(name, args)

        if status == ActionStatus.ERROR and attempt < self.max_retries:
            if self._is_transient_error(result):
                time.sleep(min(2 ** attempt, 30))
                return self._execute_with_retry(name, args, attempt + 1)

        return result, status

    def _is_transient_error(self, error_msg: str) -> bool:
        transient_patterns = [
            "timeout", "connection", "rate limit", "too many requests",
            "temporary", "unavailable", "503", "502", "504", "429"
        ]
        return any(p in error_msg.lower() for p in transient_patterns)

    def _build_messages(self, context: str) -> List[Dict]:
        messages = [
            {"role": "system", "content": INVESTIGATOR_REACT_PROMPT.format(max_iterations=self.max_iterations)},
            {"role": "user", "content": context}
        ]

        for step in self.step_chain:
            if step.action_name is None:
                messages.append({"role": "assistant", "content": step.reasoning})
            else:
                messages.append({
                    "role": "assistant",
                    "content": step.reasoning,
                    "tool_calls": [{
                        "id": f"call_{step.iteration_number}",
                        "type": "function",
                        "function": {
                            "name": step.action_name,
                            "arguments": json.dumps(step.action_input)
                        }
                    }]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": f"call_{step.iteration_number}",
                    "content": step.result or ""
                })

        return messages

    def investigate(
        self,
        bug_id: str,
        test_name: str,
        test_file: str,
        traceback: str,
        failure_summary: str,
        exception_type: str,
        sandbox_path: str
    ) -> InvestigationOutput:
        logger.info(f"Investigating bug_id: {bug_id}")

        self.step_chain = []
        self._error_counts = {}

        context = f"""\
## Failing Test
- Name: {test_name}
- File: {test_file}
- Exception: {exception_type}
- Summary: {failure_summary}
- Sandbox: {sandbox_path}

## Traceback
{traceback}
"""

        current_observation = "Starting fresh. You have access to tools. Analyze the task and take action."

        for iteration in range(self.max_iterations):
            iter_no = iteration + 1

            messages = self._build_messages(context=context)
            messages.append({
                "role": "user",
                "content": f"Current observation: {current_observation}\n\nWhat do you think and what action should you take next?"
            })

            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    temperature=0.2,
                    parallel_tool_calls=False,
                )
            except Exception as e:
                logger.error(f"OpenAI API error: {e}")
                raise

            message = response.choices[0].message
            reasoning = message.content or "(no explicit reasoning provided)"

            if not message.tool_calls:
                logger.info("Investigation complete")

                step = Step(
                    iteration_number=iter_no,
                    observation=current_observation,
                    reasoning=reasoning,
                    action_name=None,
                    action_input=None,
                    result=reasoning,
                )
                self.step_chain.append(step)

                return self._extract_investigation(bug_id, test_name)

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                result, status = self._execute_with_retry(tool_name, tool_args)

                step = Step(
                    iteration_number=iter_no,
                    observation=current_observation,
                    reasoning=reasoning,
                    action_name=tool_name,
                    action_input=tool_args,
                    result=result,
                    status=status,
                )

                current_observation = result
                self.step_chain.append(step)

                if status == ActionStatus.ERROR:
                    error_key = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                    self._error_counts[error_key] = self._error_counts.get(error_key, 0) + 1
                    if self._error_counts[error_key] >= 3:
                        logger.error(f"Circuit breaker: {tool_name}")
                        raise RuntimeError(f"Circuit breaker: repeated failures on {tool_name}")

        logger.warning("Max iterations reached")
        return self._extract_investigation(bug_id, test_name, partial=True)

    def _extract_investigation(self, bug_id: str, test_name: str, partial: bool = False) -> InvestigationOutput:
        investigation_log = []
        for step in self.step_chain:
            investigation_log.append(f"\n--- Step {step.iteration_number} [{step.status.value}] ---")
            investigation_log.append(f"Observation: {step.observation}")
            investigation_log.append(f"Thought: {step.reasoning}")
            if step.action_name:
                investigation_log.append(f"Action: {step.action_name}")
                investigation_log.append(f"Args: {json.dumps(step.action_input)}")
                investigation_log.append(f"Result:\n{step.result}")

        messages = [
            {"role": "system", "content": INVESTIGATOR_EXTRACT_PROMPT},
            {"role": "user", "content": f"""\
Investigation metadata:
- bug_id: {bug_id}
- test_name: {test_name}
- total_steps: {len(self.step_chain)}
- partial: {partial}

Investigation log:
{''.join(investigation_log)}

Extract the structured investigation report from the log above.
"""}
        ]

        try:
            response = self._client.beta.chat.completions.parse(
                model=self._model,
                messages=messages,
                response_format=InvestigationOutput,
            )
            return response.choices[0].message.parsed

        except Exception as e:
            logger.error(f"Structured extraction failed: {e}")
            return InvestigationOutput(results=[])

    def get_trace(self) -> str:
        lines = [f"Investigation Trace ({len(self.step_chain)} steps):"]
        for step in self.step_chain:
            lines.append(f"\n  Step {step.iteration_number} [{step.status.value}]")
            lines.append(f"    Observation: {step.observation}")
            lines.append(f"    Thought: {step.reasoning}")
            if step.action_name:
                lines.append(f"    Action: {step.action_name}({json.dumps(step.action_input)})")
            if step.result:
                lines.append(f"    Result: {step.result[:500]}...")
        return "\n".join(lines)
    
    def get_step_chain(self):
        return self.step_chain