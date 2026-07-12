from __future__ import annotations

import json
from pydantic import BaseModel
from openai import OpenAI
from loguru import logger

from src.tools.filesystem import read_file, list_files
from src.tools.codebase import (
    grep_codebase,
    get_function_definition,
    get_class_definition,
    get_function_callers,
    get_imports,
)


INVESTIGATE_SYSTEM = """\
You are an expert bug investigator. Your job is to find the root cause of a failing test.

## Process

1. Start by reading the failing test file and the source file mentioned in the traceback.
2. Follow the call chain — if the source calls other functions, read those too.
3. Use `get_function_callers` to find who calls the broken function.
4. Use `get_imports` to trace where symbols come from.
5. Use `grep_codebase` to search for related patterns.
6. Keep investigating until you understand the FULL root cause — not just the symptom.

## Rules

- Read every traceback frame to understand the call chain.
- Don't stop at the first file — follow the code until you find the actual bug.
- Always explain your reasoning as you go.
- When you have enough information, output your final analysis as JSON.

## Output

When you are done investigating, output ONLY a JSON object with these keys:
```json
{
  "root_cause": "Clear explanation of what's wrong and why",
  "affected_files": ["list", "of", "files", "that", "need", "changes"],
  "relevant_snippets": {"file_path": "the relevant code snippet"},
  "investigation_steps": ["Step 1: ...", "Step 2: ..."]
}
```
No markdown fences. No other text. Just the JSON."""


INVESTIGATOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file and return its content with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Relative path to the file (e.g. 'src/calculator.py')",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_codebase",
            "description": "Search all Python files for a pattern (text or regex).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Text or regex pattern to search for",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_function_definition",
            "description": "Get the full source code of a function by name using AST.",
            "parameters": {
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the function to find",
                    }
                },
                "required": ["function_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_class_definition",
            "description": "Get the full source code of a class by name using AST.",
            "parameters": {
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Name of the class to find",
                    }
                },
                "required": ["class_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_function_callers",
            "description": "Find every call site of a function across the codebase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "function_name": {
                        "type": "string",
                        "description": "Name of the function to find callers for",
                    }
                },
                "required": ["function_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_imports",
            "description": "Return all import statements from a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_file_path": {
                        "type": "string",
                        "description": "Relative path to the file (e.g. 'src/calculator.py')",
                    }
                },
                "required": ["relative_file_path"],
            },
        },
    },
]


TOOL_MAP = {
    "read_file": read_file,
    "grep_codebase": grep_codebase,
    "get_function_definition": get_function_definition,
    "get_class_definition": get_class_definition,
    "get_function_callers": get_function_callers,
    "get_imports": get_imports,
}


class InvestigationResult(BaseModel):
    root_cause: str
    affected_files: list[str]
    relevant_snippets: dict[str, str]
    investigation_steps: list[str]


class Investigator:

    def __init__(self, model: str = "gpt-4o", api_key: str = "", max_steps: int = 10):
        self.model = model
        self.client = OpenAI(api_key=api_key)
        self.max_steps = max_steps

    def _execute_tool(self, name: str, args: dict, sandbox: str) -> str:
        func = TOOL_MAP.get(name)
        if not func:
            return f"ERROR: unknown tool '{name}'"

        if "repo_path" in func.__code__.co_varnames and "repo_path" not in args:
            args["repo_path"] = sandbox

        try:
            result = func(**args)
            return str(result)
        except Exception as e:
            return f"ERROR: {name} failed: {e}"

    def _build_user_message(self, bug) -> str:
        parts = [
            f"## Failing test: {bug.test_name}",
            f"Test file: {bug.test_file}",
            f"Source file: {bug.source_file}",
            f"Exception: {bug.exception_type}",
            f"Summary: {bug.summary}",
            f"Severity: {bug.severity}",
        ]

        if bug.traceback:
            parts.append("\n## Traceback frames:")
            for i, frame in enumerate(bug.traceback):
                parts.append(f"  {i + 1}. {frame.file}:{frame.line_no} in {frame.function}")
                if frame.code:
                    parts.append(f"     {frame.code}")

        if bug.raw_output:
            parts.append(f"\n## Raw output:\n{bug.raw_output}")

        parts.append(
            "\nInvestigate this bug. Read the source files, trace the call chain, "
            "and find the root cause. Output your final analysis as JSON."
        )

        return "\n".join(parts)

    def investigate(self, bug, sandbox: str) -> InvestigationResult:
        messages = [
            {"role": "system", "content": INVESTIGATE_SYSTEM},
            {"role": "user", "content": self._build_user_message(bug)},
        ]

        steps_log = []

        for step in range(self.max_steps):
            logger.info(f"Investigation step {step + 1}/{self.max_steps}")

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=INVESTIGATOR_TOOLS,
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                logger.info("Investigation complete — parsing result")
                try:
                    result = InvestigationResult.model_validate_json(msg.content)
                    return result
                except Exception:
                    try:
                        data = json.loads(msg.content)
                        return InvestigationResult(**data)
                    except Exception as e:
                        logger.error(f"Failed to parse investigation result: {e}")
                        return InvestigationResult(
                            root_cause=f"Investigation completed but output could not be parsed: {e}",
                            affected_files=[bug.source_file],
                            relevant_snippets={},
                            investigation_steps=steps_log,
                        )

            messages.append(msg)

            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                logger.info(f"  Tool call: {name}({args})")
                steps_log.append(f"Called {name}({args})")

                result = self._execute_tool(name, args, sandbox)

                preview = result[:200] + "..." if len(result) > 200 else result
                logger.info(f"  Result: {preview}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        logger.warning("Investigation reached max steps")
        return InvestigationResult(
            root_cause="Investigation exceeded maximum steps without conclusion",
            affected_files=[bug.source_file],
            relevant_snippets={},
            investigation_steps=steps_log,
        )
