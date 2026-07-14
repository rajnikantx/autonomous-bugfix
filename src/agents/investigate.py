"""
Codebase Investigator — ReAct Agent with End-Assembly Structured Output
=======================================================================

Investigates bugs using tools, accumulates raw data deterministically,
assembles structured InvestigationResult at the end with one LLM call.

Requirements:
    pip install openai pydantic

Usage:
    agent = ReActAgent(openai_api_key="sk-...")
    result = agent.run(
        "Investigate test_login_fails. Error: NoneType in src/auth.py. Sandbox: /home/user/project",
        response_model=InvestigationOutput
    )
    print(result["answer"].results[0].root_cause)
"""

import ast
import json
import os
import re
import subprocess
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Type, TypeVar

from loguru import logger
from openai import OpenAI
from pydantic import BaseModel, Field

from src.config import settings


# =============================================================================
# STRUCTURED OUTPUT SCHEMAS
# =============================================================================

class InvestigationResult(BaseModel):
    bug_id: str = Field(description="ID of the bug being investigated")
    test_name: str = Field(description="Name of the failing test")
    root_cause: str = Field(description="1-2 sentence explanation of the actual bug")
    affected_files: list[str] = Field(description="All files that need changing")
    affected_lines: dict[str, list[int]] = Field(
        description="File path mapped to line numbers of interest",
        default_factory=dict
    )
    affected_functions: list[str] = Field(
        description="Fully qualified function/method names",
        default_factory=list
    )
    affected_classes: list[str] = Field(
        description="Fully qualified class names",
        default_factory=list
    )
    code_snippets: dict[str, str] = Field(
        description="File path mapped to relevant code blocks",
        default_factory=dict
    )
    file_reasoning: dict[str, str] = Field(
        description="File path mapped to why this file is linked",
        default_factory=dict
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence in the root cause analysis"
    )
    reasoning_trace: list[str] = Field(
        description="Steps the investigator took"
    )


class InvestigationOutput(BaseModel):
    results: list[InvestigationResult] = Field(
        description="The complete list of investigation results for the tracked bugs."
    )


T = TypeVar("T", bound=BaseModel)


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

INVESTIGATOR_SYSTEM = """\
You are a senior code investigator. Your job is to find the root cause of a test failure by exploring the codebase.

## Tools

You have access to these tools:

- `extract_snippet(file_path, line_no, radius=10)` — Read lines around a specific line. The crash line is marked with `>>>`. Use this FIRST for any file — it's fast and gives context.
- `read_file(file_path)` — Read the full content of a file with line numbers. Use for small files or when you need the complete picture.
- `grep_codebase(pattern, sandbox_path)` — Search for text/regex across all .py files. Use to find definitions, usages, and similar code.
- `get_function_definition(function_name, sandbox_path)` — Get the COMPLETE source of a function using AST parsing. Use to read the full function body.
- `get_class_definition(class_name, sandbox_path)` — Get the COMPLETE source of a class with method summary. Use for class-related bugs.
- `get_function_callers(function_name, sandbox_path)` — Find ALL call sites of a function using AST. More precise than grep for finding who calls what.
- `get_functions_of_file(file_path)` — Get an overview of all functions/classes in a file. Use to quickly understand file structure.
- `get_imports_of_file(file_path)` — Get all imports from a file. Use when tracing where symbols come from.

IMPORTANT: All tools that take `sandbox_path` need the full sandbox directory path, which is provided in the failing test context below.

## Process — YOU MUST FOLLOW ALL STEPS

You MUST make at least 5 tool calls before returning your final answer. Do NOT stop early.

### Step 1: Understand the test failure
- Use `extract_snippet` on the test file at the failing line to see context.
- Understand what the test expects and what the error says.

### Step 2: Read source files from the traceback
- Use `extract_snippet` on each source file mentioned in the traceback at the error line.
- Use `get_function_definition` to read the full body of any functions called in the failing code.

### Step 3: Trace the call chain
- For every function called in the failing code, use `get_function_definition` to read it.
- If a function calls other functions, trace THOSE too. Follow the chain until you reach leaf functions.
- Use `get_function_callers` to see who else calls the buggy function.

### Step 4: Check related code
- Use `grep_codebase` to find:
  - All callers of the buggy function
  - Similar functions that might have the same bug
  - Any TODOs or FIXMEs near the buggy code
- Use `get_imports_of_file` if you need to trace where a symbol comes from.

### Step 5: Verify your hypothesis
- Use `extract_snippet` to re-read the specific lines you think are wrong.
- Check if there are any conditions, edge cases, or dependencies you missed.

### Step 6: Return your investigation
When you have enough information, stop calling tools and write a clear, detailed summary of your findings. The system will extract the structured report automatically.

## Rules

- Make at least 5 tool calls before returning. Read more if needed.
- ALWAYS use extract_snippet first — don't jump to read_file for large files.
- ALWAYS trace the full call chain — do not stop at the first function you find.
- List EVERY file you read that's relevant, not just the one with the obvious bug.
- If you cannot determine the root cause, say so clearly.
- Do not guess. If the traceback is unclear, say so.
"""


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "extract_snippet",
            "description": "Read lines around a specific line. The crash line is marked with >>>. Use this FIRST for any file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "line_no": {"type": "integer"},
                    "radius": {"type": "integer", "default": 10}
                },
                "required": ["file_path", "line_no"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full content of a file with line numbers. Use for small files or when you need the complete picture.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "grep_codebase",
            "description": "Search for text/regex across all .py files. Use to find definitions, usages, and similar code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "sandbox_path": {"type": "string"}
                },
                "required": ["pattern", "sandbox_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_function_definition",
            "description": "Get the COMPLETE source of a function using AST parsing. Use to read the full function body.",
            "parameters": {
                "type": "object",
                "properties": {
                    "function_name": {"type": "string"},
                    "sandbox_path": {"type": "string"}
                },
                "required": ["function_name", "sandbox_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_class_definition",
            "description": "Get the COMPLETE source of a class with method summary. Use for class-related bugs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_name": {"type": "string"},
                    "sandbox_path": {"type": "string"}
                },
                "required": ["class_name", "sandbox_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_function_callers",
            "description": "Find ALL call sites of a function using AST. More precise than grep for finding who calls what.",
            "parameters": {
                "type": "object",
                "properties": {
                    "function_name": {"type": "string"},
                    "sandbox_path": {"type": "string"}
                },
                "required": ["function_name", "sandbox_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_functions_of_file",
            "description": "Get an overview of all functions/classes in a file. Use to quickly understand file structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_imports_of_file",
            "description": "Get all imports from a file. Use when tracing where symbols come from.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"}
                },
                "required": ["file_path"]
            }
        }
    }
]


# =============================================================================
# TOOL IMPLEMENTATIONS
# =============================================================================

def tool_extract_snippet(file_path: str, line_no: int, radius: int = 10) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        total = len(lines)
        start = max(0, line_no - radius - 1)
        end = min(total, line_no + radius)
        output = [f"Snippet from {file_path} (lines {start + 1}-{end}):"]
        for i in range(start, end):
            marker = ">>> " if i == line_no - 1 else "    "
            output.append(f"{marker}{i + 1:4d}: {lines[i].rstrip()}")
        return "\n".join(output)
    except Exception as e:
        return f"Error: {str(e)}"


def tool_read_file(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        output = [f"Full file: {file_path}"]
        for i, line in enumerate(lines, 1):
            output.append(f"{i:4d}: {line.rstrip()}")
        return "\n".join(output)
    except FileNotFoundError:
        return f"Error: File '{file_path}' not found."
    except PermissionError:
        return f"Error: Permission denied for '{file_path}'."
    except Exception as e:
        return f"Error reading file: {str(e)}"


def tool_grep_codebase(pattern: str, sandbox_path: str) -> str:
    try:
        cmd = ["rg", "-n", "--no-heading", "-g", "*.py", pattern, sandbox_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split("\n")[:50]
            return "\n".join(lines)
        if result.returncode == 1:
            return "No matches found."
    except FileNotFoundError:
        pass

    try:
        cmd = ["grep", "-rn", "--include", "*.py", pattern, sandbox_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout:
            lines = result.stdout.strip().split("\n")[:50]
            return "\n".join(lines)
        return "No matches found."
    except subprocess.TimeoutExpired:
        return "Error: Search timed out."
    except Exception as e:
        return f"Search error: {str(e)}"


def _find_py_files(sandbox_path: str):
    for root, _, files in os.walk(sandbox_path):
        for fname in files:
            if fname.endswith(".py"):
                yield os.path.join(root, fname)


def tool_get_function_definition(function_name: str, sandbox_path: str) -> str:
    matches = []
    for fpath in _find_py_files(sandbox_path):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
            lines = source.splitlines()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                    start = node.lineno - 1
                    end = node.end_lineno
                    code = "\n".join(f"{i + 1:4d}: {lines[i]}" for i in range(start, end))
                    matches.append(f"Found in {fpath}:\n{code}")
        except Exception:
            continue
    return "\n\n".join(matches) if matches else f"Function '{function_name}' not found."


def tool_get_class_definition(class_name: str, sandbox_path: str) -> str:
    matches = []
    for fpath in _find_py_files(sandbox_path):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
            lines = source.splitlines()
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    start = node.lineno - 1
                    end = node.end_lineno
                    methods = [
                        n.name for n in node.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ]
                    code = "\n".join(f"{i + 1:4d}: {lines[i]}" for i in range(start, end))
                    matches.append(
                        f"Found in {fpath}:\n"
                        f"Methods: {', '.join(methods)}\n"
                        f"{code}"
                    )
        except Exception:
            continue
    return "\n\n".join(matches) if matches else f"Class '{class_name}' not found."


def tool_get_function_callers(function_name: str, sandbox_path: str) -> str:
    results = []
    for fpath in _find_py_files(sandbox_path):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source)
            file_lines = source.splitlines()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    match = False
                    if isinstance(node.func, ast.Name) and node.func.id == function_name:
                        match = True
                    elif isinstance(node.func, ast.Attribute) and node.func.attr == function_name:
                        match = True
                    if match:
                        line = file_lines[node.lineno - 1].strip()
                        results.append(f"{fpath}:{node.lineno}: {line}")
        except Exception:
            continue
    return "\n".join(results) if results else f"No callers of '{function_name}' found."


def tool_get_functions_of_file(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        funcs = []
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append(f"  {node.name} (line {node.lineno})")
            elif isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append(f"  {node.name} (line {node.lineno}) — methods: {', '.join(methods)}")
        output = []
        if funcs:
            output.append(f"Functions in {file_path}:")
            output.extend(sorted(funcs))
        if classes:
            output.append(f"\nClasses in {file_path}:")
            output.extend(sorted(classes))
        return "\n".join(output) if output else f"No functions/classes found in {file_path}."
    except Exception as e:
        return f"Error: {str(e)}"


def tool_get_imports_of_file(file_path: str) -> str:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(f"  import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or "."
                names = ", ".join(
                    f"{a.name}" + (f" as {a.asname}" if a.asname else "")
                    for a in node.names
                )
                imports.append(f"  from {module} import {names}")
        return f"Imports in {file_path}:\n" + "\n".join(imports) if imports else f"No imports found in {file_path}."
    except Exception as e:
        return f"Error: {str(e)}"


TOOL_DISPATCH = {
    "extract_snippet": tool_extract_snippet,
    "read_file": tool_read_file,
    "grep_codebase": tool_grep_codebase,
    "get_function_definition": tool_get_function_definition,
    "get_class_definition": tool_get_class_definition,
    "get_function_callers": tool_get_function_callers,
    "get_functions_of_file": tool_get_functions_of_file,
    "get_imports_of_file": tool_get_imports_of_file,
}


# =============================================================================
# MERGED DATACLASS: Step + Investigation State
# =============================================================================

class ActionStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    MAX_RETRIES = "max_retries"


@dataclass
class InvestigationStep:
    """
    Merged dataclass: ReAct execution trace + raw investigation data.
    Structured fields (root_cause, confidence, file_reasoning) assembled at end.
    """
    # ── ReAct execution trace ──
    step_number: int
    observation: str
    reasoning: str
    action_name: Optional[str] = None
    action_input: Optional[Dict] = None
    tool_result: Optional[str] = None
    status: ActionStatus = ActionStatus.SUCCESS
    timestamp: datetime = field(default_factory=datetime.now)
    retry_history: List[Dict] = field(default_factory=list)
    
    # ── Conversation history snapshots ──
    messages_before: List[Dict] = field(default_factory=list)
    messages_after: List[Dict] = field(default_factory=list)
    
    # ── Raw investigation data (accumulated deterministically) ──
    files_seen: List[str] = field(default_factory=list)
    functions_seen: List[str] = field(default_factory=list)
    classes_seen: List[str] = field(default_factory=list)
    lines_seen: Dict[str, List[int]] = field(default_factory=dict)
    snippets_seen: Dict[str, str] = field(default_factory=dict)


# =============================================================================
# REACT AGENT
# =============================================================================

class ReActAgent:
    def __init__(
        self,
        openai_api_key: str,
        model: str = "gpt-4o-2024-08-06",
        max_iterations: int = 25,
        max_retries: int = 3
    ):
        self.client = OpenAI(api_key=openai_api_key)
        self.model = model
        self.max_iterations = max_iterations
        self.max_retries = max_retries
        self.step_chain: List[InvestigationStep] = []
        self._error_counts: Dict[str, int] = {}

    def _build_messages(self, task: str) -> List[Dict]:
        messages = [
            {"role": "system", "content": INVESTIGATOR_SYSTEM},
            {"role": "user", "content": task}
        ]

        for step in self.step_chain:
            if step.action_name is None:
                messages.append({"role": "assistant", "content": step.reasoning})
            else:
                messages.append({
                    "role": "assistant",
                    "content": step.reasoning,
                    "tool_calls": [{
                        "id": f"call_{step.step_number}",
                        "type": "function",
                        "function": {
                            "name": step.action_name,
                            "arguments": json.dumps(step.action_input)
                        }
                    }]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": f"call_{step.step_number}",
                    "content": step.tool_result or ""
                })

        return messages

    def _is_transient_error(self, error_msg: str) -> bool:
        transient_patterns = [
            "timeout", "connection", "rate limit", "too many requests",
            "temporary", "unavailable", "503", "502", "504", "429"
        ]
        return any(p in error_msg.lower() for p in transient_patterns)

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> Tuple[str, ActionStatus]:
        tool_func = TOOL_DISPATCH.get(name)
        if not tool_func:
            return f"Error: Unknown tool '{name}'", ActionStatus.ERROR

        try:
            result = tool_func(**args)
            return str(result), ActionStatus.SUCCESS
        except Exception as e:
            return f"Error executing {name}: {str(e)}", ActionStatus.ERROR

    def _execute_with_retry(self, name: str, args: Dict, attempt: int = 1, history: List[Dict] = None) -> Tuple[str, ActionStatus, List[Dict]]:
        history = history or []
        result, status = self._execute_tool(name, args)

        if status == ActionStatus.ERROR and attempt < self.max_retries:
            is_transient = self._is_transient_error(result)
            if not is_transient:
                history.append({
                    "attempt": attempt,
                    "tool_name": name,
                    "tool_args": args,
                    "error": result,
                    "is_transient": False,
                    "retried": False,
                    "sleep_seconds": 0
                })
                return result, status, history

            sleep_seconds = min(2 ** attempt, 30)
            history.append({
                "attempt": attempt,
                "tool_name": name,
                "tool_args": args,
                "error": result,
                "is_transient": True,
                "retried": True,
                "sleep_seconds": sleep_seconds
            })
            time.sleep(sleep_seconds)
            return self._execute_with_retry(name, args, attempt + 1, history)

        if status == ActionStatus.ERROR and attempt >= self.max_retries:
            history.append({
                "attempt": attempt,
                "tool_name": name,
                "tool_args": args,
                "error": result,
                "is_transient": self._is_transient_error(result),
                "retried": False,
                "sleep_seconds": 0
            })

        return result, status, history

    def _extract_raw_from_tool(self, tool_name: str, tool_args: Dict, tool_result: str) -> Dict:
        """Deterministically parse raw data from tool result. No LLM."""
        raw = {
            "files": [],
            "functions": [],
            "classes": [],
            "lines": {},
            "snippets": {}
        }

        if tool_name == "extract_snippet":
            raw["files"].append(tool_args["file_path"])
            line_no = tool_args["line_no"]
            raw["lines"][tool_args["file_path"]] = [line_no]
            # Extract snippet content for code_snippets
            raw["snippets"][tool_args["file_path"]] = tool_result[:2000]

        elif tool_name == "read_file":
            raw["files"].append(tool_args["file_path"])
            raw["snippets"][tool_args["file_path"]] = tool_result[:2000]

        elif tool_name == "get_function_definition":
            match = re.search(r'Found in (\S+):', tool_result)
            if match:
                raw["files"].append(match.group(1))
            raw["functions"].append(tool_args["function_name"])
            if match:
                raw["snippets"][match.group(1)] = tool_result[:2000]

        elif tool_name == "get_class_definition":
            match = re.search(r'Found in (\S+):', tool_result)
            if match:
                raw["files"].append(match.group(1))
            raw["classes"].append(tool_args["class_name"])
            if match:
                raw["snippets"][match.group(1)] = tool_result[:2000]

        elif tool_name == "get_function_callers":
            for line in tool_result.split("\n"):
                if ":" in line:
                    filepath = line.split(":")[0]
                    if filepath and filepath not in raw["files"]:
                        raw["files"].append(filepath)

        elif tool_name == "grep_codebase":
            for line in tool_result.split("\n"):
                if ":" in line:
                    filepath = line.split(":")[0]
                    if filepath and filepath not in raw["files"]:
                        raw["files"].append(filepath)

        elif tool_name in ("get_functions_of_file", "get_imports_of_file"):
            raw["files"].append(tool_args["file_path"])

        return raw

    def _assemble_investigation(self, task: str, response_model: Type[T]) -> T:
        """
        ONE LLM call at the end.
        Input: full ReAct history + accumulated raw data.
        Output: complete structured InvestigationResult.
        """
        # Build accumulated raw data summary
        all_files = list(dict.fromkeys(f for step in self.step_chain for f in step.files_seen))
        all_functions = list(dict.fromkeys(fn for step in self.step_chain for fn in step.functions_seen))
        all_classes = list(dict.fromkeys(c for step in self.step_chain for c in step.classes_seen))
        
        all_lines = {}
        for step in self.step_chain:
            for filepath, lines in step.lines_seen.items():
                if filepath not in all_lines:
                    all_lines[filepath] = []
                all_lines[filepath] = list(dict.fromkeys(all_lines[filepath] + lines))
        
        all_snippets = {}
        for step in self.step_chain:
            all_snippets.update(step.snippets_seen)

        raw_summary = f"""
ACCUMULATED RAW DATA FROM INVESTIGATION:
- Files seen: {all_files}
- Functions seen: {all_functions}
- Classes seen: {all_classes}
- Lines of interest: {all_lines}
- Code snippets available for: {list(all_snippets.keys())}

FULL INVESTIGATION HISTORY:
"""

        # Add full conversation history
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a structured data assembler. "
                    "Review the full investigation history and accumulated raw data below. "
                    "Produce the final structured investigation report. "
                    "Be faithful to the evidence. Do not hallucinate files, line numbers, or code."
                )
            }
        ]

        # Include full ReAct history (skip the investigator system prompt at index 0)
        history_messages = self._build_messages(task)
        messages.extend(history_messages[1:])

        # Append raw summary as final user message
        messages.append({
            "role": "user",
            "content": (
                raw_summary + 
                f"\n\nTask: {task}\n\n"
                f"Assemble the final structured investigation report."
            )
        })

        try:
            completion = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=messages,
                response_format=response_model,
            )
            return completion.choices[0].message.parsed
        except Exception as e:
            # Fallback: create minimal valid instance
            defaults = {field: "" for field in response_model.model_fields.keys()}
            if "results" in defaults:
                defaults["results"] = []
            return response_model(**defaults)

    def run(self, task: str, response_model: Type[T] = None, initial_observation: str = "") -> Dict[str, Any]:
        current_observation = initial_observation or "Starting fresh. You have access to codebase investigation tools."

        for iteration in range(self.max_iterations):
            step_num = iteration + 1

            messages = self._build_messages(task)
            messages_before = list(messages)

            messages.append({
                "role": "user",
                "content": f"Current observation: {current_observation}\n\nWhat do you think and what action should you take next?"
            })

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    temperature=0.2,
                    parallel_tool_calls=False,
                )
            except Exception as e:
                return {
                    "success": False,
                    "answer": None,
                    "error": f"OpenAI API error: {str(e)}",
                    "iterations": step_num,
                    "step_chain": self.step_chain
                }

            message = response.choices[0].message
            reasoning = message.content or "(no explicit reasoning provided)"

            # Natural termination: no tool calls = done
            if not message.tool_calls:
                messages_after = self._build_messages(task)
                messages_after.append({"role": "assistant", "content": reasoning})

                self.step_chain.append(InvestigationStep(
                    step_number=step_num,
                    observation=current_observation,
                    reasoning=reasoning,
                    action_name=None,
                    action_input=None,
                    tool_result=reasoning,
                    messages_before=messages_before,
                    messages_after=messages_after
                ))

                # FINAL ASSEMBLY: one LLM call with full history + raw data
                if response_model is not None:
                    structured = self._assemble_investigation(task, response_model)
                    return {
                        "success": True,
                        "answer": structured,
                        "raw_answer": reasoning,
                        "iterations": step_num,
                        "step_chain": self.step_chain
                    }

                return {
                    "success": True,
                    "answer": reasoning,
                    "iterations": step_num,
                    "step_chain": self.step_chain
                }

            # Process tool calls
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                result, status, retry_history = self._execute_with_retry(tool_name, tool_args)

                # Extract raw data deterministically (no LLM)
                raw_data = self._extract_raw_from_tool(tool_name, tool_args, result)

                messages_after = self._build_messages(task)
                messages_after.append({
                    "role": "assistant",
                    "content": reasoning,
                    "tool_calls": [{
                        "id": f"call_{step_num}",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args)
                        }
                    }]
                })
                messages_after.append({
                    "role": "tool",
                    "tool_call_id": f"call_{step_num}",
                    "content": result or ""
                })

                self.step_chain.append(InvestigationStep(
                    step_number=step_num,
                    observation=current_observation,
                    reasoning=reasoning,
                    action_name=tool_name,
                    action_input=tool_args,
                    tool_result=result,
                    status=status,
                    messages_before=messages_before,
                    messages_after=messages_after,
                    retry_history=retry_history,
                    files_seen=raw_data["files"],
                    functions_seen=raw_data["functions"],
                    classes_seen=raw_data["classes"],
                    lines_seen=raw_data["lines"],
                    snippets_seen=raw_data["snippets"]
                ))

                current_observation = result

                if status == ActionStatus.ERROR:
                    error_key = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"
                    self._error_counts[error_key] = self._error_counts.get(error_key, 0) + 1
                    if self._error_counts[error_key] >= 3:
                        return {
                            "success": False,
                            "answer": None,
                            "error": f"Circuit breaker: repeated failures on {tool_name}",
                            "iterations": step_num,
                            "step_chain": self.step_chain
                        }

        last_reasoning = self.step_chain[-1].reasoning if self.step_chain else None
        return {
            "success": False,
            "answer": last_reasoning,
            "error": "Max iterations reached",
            "partial": True,
            "iterations": self.max_iterations,
            "step_chain": self.step_chain
        }

    def get_trace(self) -> str:
        lines = [f"Execution Trace ({len(self.step_chain)} steps):"]
        for step in self.step_chain:
            lines.append(f"\n  Step {step.step_number} [{step.status.value}]")
            lines.append(f"    Observation: {step.observation[:120]}...")
            lines.append(f"    Thought: {step.reasoning[:120]}...")
            if step.action_name:
                lines.append(f"    Action: {step.action_name}({json.dumps(step.action_input)})")
            if step.tool_result:
                lines.append(f"    Result: {step.tool_result[:200]}...")
            lines.append(f"    Raw data: files={step.files_seen}, functions={step.functions_seen}, classes={step.classes_seen}")
            if step.retry_history:
                lines.append(f"    Retries: {len(step.retry_history)}")
            lines.append(f"    History: before={len(step.messages_before)} after={len(step.messages_after)}")
        return "\n".join(lines)


# =============================================================================
# WRAPPER CLASS — bridges ReActAgent to graph node interface
# =============================================================================

class Investigate:
    """Thin wrapper that adapts ReActAgent to the interface expected by the graph node."""

    def __init__(self):
        self._agent = ReActAgent(
            openai_api_key=settings.OPENAI_API_KEY,
            model=settings.INVESTIGATE_MODEL,
            max_iterations=25,
            max_retries=3,
        )

    def run(
        self,
        bug_id: str,
        test_name: str,
        test_file: str,
        traceback: str,
        failure_summary: str,
        exception_type: str,
        sandbox_path: str,
    ) -> InvestigationResult:
        task = (
            f"Investigate the failing test '{test_name}' in '{test_file}'.\n"
            f"Exception type: {exception_type}\n"
            f"Summary: {failure_summary}\n"
            f"Sandbox path: {sandbox_path}\n"
            f"Bug ID: {bug_id}\n\n"
            f"Traceback:\n{traceback}"
        )

        logger.info(
            f"Investigator starting: bug_id={bug_id}, test={test_name}, "
            f"file={test_file}, exception={exception_type}"
        )

        result = self._agent.run(
            task=task,
            response_model=InvestigationOutput,
            initial_observation=f"Analyzing test failure: {test_name}",
        )

        if not result["success"]:
            logger.warning(f"Investigation failed: {result.get('error')}")
            return InvestigationResult(
                bug_id=bug_id,
                test_name=test_name,
                root_cause="Investigation failed: " + result.get("error", "unknown error"),
                affected_files=[],
                affected_lines={},
                affected_functions=[],
                affected_classes=[],
                code_snippets={},
                file_reasoning={},
                confidence="low",
                reasoning_trace=[s.reasoning for s in result.get("step_chain", [])],
            )

        output: InvestigationOutput = result["answer"]
        if not output.results:
            logger.warning("Investigation returned empty results")
            return InvestigationResult(
                bug_id=bug_id,
                test_name=test_name,
                root_cause="No investigation results produced",
                affected_files=[],
                affected_lines={},
                affected_functions=[],
                affected_classes=[],
                code_snippets={},
                file_reasoning={},
                confidence="low",
                reasoning_trace=[s.reasoning for s in result.get("step_chain", [])],
            )

        inv = output.results[0]
        inv.bug_id = bug_id
        inv.test_name = test_name

        logger.info(
            f"Investigation complete: confidence={inv.confidence}, "
            f"affected_files={inv.affected_files}, root_cause={inv.root_cause[:100]}"
        )

        return inv


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: Set OPENAI_API_KEY environment variable")
        return

    agent = ReActAgent(
        openai_api_key=api_key,
        model="gpt-4o-2024-08-06",
        max_iterations=25
    )

    result = agent.run(
        task=(
            "Investigate the failing test 'test_login_fails'. "
            "The error trace mentions 'NoneType' in src/auth.py. "
            "Sandbox path: /home/user/project"
        ),
        response_model=InvestigationOutput,
        initial_observation="Working directory: /home/user/project"
    )

    if result["success"]:
        output: InvestigationOutput = result["answer"]
        print(f"Found {len(output.results)} investigation result(s)\n")

        for r in output.results:
            print(f"Bug ID: {r.bug_id}")
            print(f"Test: {r.test_name}")
            print(f"Root Cause: {r.root_cause}")
            print(f"Confidence: {r.confidence}")
            print(f"Affected Files: {r.affected_files}")
            print(f"Affected Lines: {r.affected_lines}")
            print(f"Affected Functions: {r.affected_functions}")
            print(f"Affected Classes: {r.affected_classes}")
            print(f"Code Snippets keys: {list(r.code_snippets.keys())}")
            print(f"File Reasoning: {r.file_reasoning}")
            print(f"Reasoning Trace: {r.reasoning_trace}")
            print("-" * 50)
    else:
        print(f"Failed: {result['error']}")
        print(f"Partial answer: {result.get('answer')}")

    print(f"\nTrace:\n{agent.get_trace()}")


if __name__ == "__main__":
    main()