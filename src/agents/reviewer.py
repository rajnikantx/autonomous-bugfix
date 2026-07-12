from __future__ import annotations

import inspect
import json
from pydantic import BaseModel
from openai import OpenAI
from loguru import logger

from src.tools.filesystem import read_file
from src.tools.tool_registry import get_agent_tools


REVIEW_SYSTEM = """\
You are a senior code reviewer. You review proposed code fixes before they are applied.

## Process

1. Read the proposed fix (old_code → new_code).
2. Read the investigation context (root cause, affected files).
3. Optionally read the full file to check for side effects.
4. Decide: approve or reject.

## Review criteria

- **Correctness**: Does the fix actually address the root cause?
- **Side effects**: Could this change break other parts of the code?
- **Style**: Does it match the existing code style?
- **Minimalism**: Is it the smallest possible fix? No unnecessary changes?
- **Edge cases**: Are edge cases handled?

## Output

Output ONLY a JSON object:
```json
{
  "decision": "approve | reject",
  "summary": "Brief explanation of your review",
  "objections": ["list of specific issues if rejected"],
  "suggestions": ["list of improvements if approved"]
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


REVIEWER_TOOLS = _generate_tool_schemas("reviewer")


class ReviewResult(BaseModel):
    decision: str
    summary: str
    objections: list[str]
    suggestions: list[str]


class Reviewer:

    def __init__(self, model: str = "gpt-4o", api_key: str = "", max_steps: int = 3, temperature: float = 0.0):
        self.model = model
        self.client = OpenAI(api_key=api_key)
        self.max_steps = max_steps
        self._tool_map = {
            "read_file": read_file,
        }
        self.temperature = temperature

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

    def review(self, fix, root_cause: str, sandbox: str) -> ReviewResult:
        messages = [
            {"role": "system", "content": REVIEW_SYSTEM},
            {"role": "user", "content": self._build_review_message(fix, root_cause)},
        ]

        for step in range(self.max_steps):
            logger.info(f"Review step {step + 1}/{self.max_steps}")

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=REVIEWER_TOOLS,
                temperature=self.temperature,
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                logger.info("Review complete — parsing result")
                try:
                    result = ReviewResult.model_validate_json(msg.content)
                    return result
                except Exception:
                    try:
                        data = json.loads(msg.content)
                        return ReviewResult(**data)
                    except Exception as e:
                        logger.error(f"Failed to parse review result: {e}")
                        return ReviewResult(
                            decision="approve",
                            summary=f"Review completed but output could not be parsed: {e}",
                            objections=[],
                            suggestions=[],
                        )

            messages.append(msg)

            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                logger.info(f"  Review tool call: {name}({args})")

                result = self._execute_tool(name, args, sandbox)

                preview = result[:200] + "..." if len(result) > 200 else result
                logger.info(f"  Result: {preview}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        logger.warning("Review reached max steps — defaulting to approve")
        return ReviewResult(
            decision="approve",
            summary="Review reached max steps — defaulting to approve",
            objections=[],
            suggestions=[],
        )

    def _build_review_message(self, fix, root_cause: str) -> str:
        parts = [
            "## Proposed fix",
            f"File: {fix.file_path}",
            "",
            "### Code to replace (old_code):",
            f"```python\n{fix.old_code}\n```",
            "",
            "### Replacement code (new_code):",
            f"```python\n{fix.new_code}\n```",
            "",
            f"### Explanation: {fix.explanation}",
            "",
            "## Root cause analysis",
            root_cause,
            "",
            "Review this fix. Use read_file if you need to see the full file context.",
            "Output your review as JSON.",
        ]

        return "\n".join(parts)
