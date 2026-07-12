from __future__ import annotations

import inspect
import json
from pydantic import BaseModel
from openai import OpenAI
from loguru import logger

from src.tools.filesystem import read_file
from src.tools.tool_registry import get_agent_tools


FIX_SYSTEM = """\
You are an expert code fixer. Given a bug report, root cause analysis, and source code, generate a precise code fix.

## Instructions

1. Read the affected source file using the `read_file` tool.
2. Identify the exact lines that need to change.
3. Generate a fix that:
   - Changes the MINIMUM amount of code necessary.
   - Preserves existing code style and conventions.
   - Does not add unrelated changes.
   - Handles edge cases mentioned in the investigation.
4. Your fix will be applied as a string replacement — `old_code` must appear EXACTLY ONCE in the file.

## Output

Output ONLY a JSON object with these keys:
```json
{
  "file_path": "relative path to the file to fix",
  "old_code": "the exact code to replace (must be unique in the file)",
  "new_code": "the replacement code",
  "explanation": "brief explanation of what the fix does and why"
}
```
No markdown fences. No other text. Just the JSON."""


def _generate_tool_schemas(agent_name: str) -> list[dict]:
    """Auto-generate OpenAI function schemas from the tool registry."""
    tools = get_agent_tools(agent_name)
    schemas = []
    for tool in tools:
        sig = inspect.signature(tool.callable)
        params = {}
        required = []
        for name, param in sig.parameters.items():
            if name == "repo_path":
                continue
            params[name] = {"type": "string", "description": f"Parameter: {name}"}
            if param.default is inspect.Parameter.empty:
                required.append(name)
        schemas.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": params,
                    "required": required,
                },
            },
        })
    return schemas


FIXER_TOOLS = _generate_tool_schemas("fixer")


class FixResult(BaseModel):
    file_path: str
    old_code: str
    new_code: str
    explanation: str


class Fixer:

    def __init__(self, model: str = "gpt-4o", api_key: str = "", max_steps: int = 5):
        self.model = model
        self.client = OpenAI(api_key=api_key)
        self.max_steps = max_steps
        self._tool_map = {
            "read_file": read_file,
        }

    def _execute_tool(self, name: str, args: dict, sandbox: str) -> str:
        func = self._tool_map.get(name)
        if not func:
            return f"ERROR: unknown tool '{name}'"

        if "repo_path" in func.__code__.co_varnames and "repo_path" not in args:
            args["repo_path"] = sandbox

        try:
            result = func(**args)
            return str(result)
        except Exception as e:
            return f"ERROR: {name} failed: {e}"

    def _build_user_message(self, bug, root_cause: str, affected_files: list[str], relevant_snippets: dict[str, str]) -> str:
        parts = [
            f"## Failing test: {bug.test_name}",
            f"Test file: {bug.test_file}",
            f"Source file: {bug.source_file}",
            f"Exception: {bug.exception_type}",
            f"Summary: {bug.summary}",
            "",
            "## Root cause analysis",
            root_cause,
            "",
            f"## Affected files: {', '.join(affected_files)}",
        ]

        if relevant_snippets:
            parts.append("\n## Relevant code snippets:")
            for path, snippet in relevant_snippets.items():
                parts.append(f"### {path}\n```python\n{snippet}\n```")

        if bug.traceback:
            parts.append("\n## Traceback:")
            for frame in bug.traceback:
                parts.append(f"  {frame.file}:{frame.line_no} in {frame.function}")

        parts.append(
            "\nRead the affected file and generate a precise fix. "
            "Output your fix as JSON."
        )

        return "\n".join(parts)

    def propose_fix(self, bug, root_cause: str, affected_files: list[str], relevant_snippets: dict[str, str], sandbox: str) -> FixResult:
        messages = [
            {"role": "system", "content": FIX_SYSTEM},
            {"role": "user", "content": self._build_user_message(bug, root_cause, affected_files, relevant_snippets)},
        ]

        for step in range(self.max_steps):
            logger.info(f"Fix generation step {step + 1}/{self.max_steps}")

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=FIXER_TOOLS,
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                logger.info("Fix generated — parsing result")
                try:
                    result = FixResult.model_validate_json(msg.content)
                    return result
                except Exception:
                    try:
                        data = json.loads(msg.content)
                        return FixResult(**data)
                    except Exception as e:
                        logger.error(f"Failed to parse fix result: {e}")
                        return FixResult(
                            file_path=bug.source_file,
                            old_code="",
                            new_code="",
                            explanation=f"Fix generated but output could not be parsed: {e}",
                        )

            messages.append(msg)

            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                logger.info(f"  Tool call: {name}({args})")

                result = self._execute_tool(name, args, sandbox)

                preview = result[:200] + "..." if len(result) > 200 else result
                logger.info(f"  Result: {preview}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        logger.warning("Fix generation reached max steps")
        return FixResult(
            file_path=bug.source_file,
            old_code="",
            new_code="",
            explanation="Fix generation exceeded maximum steps",
        )
