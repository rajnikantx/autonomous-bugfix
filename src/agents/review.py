import json
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from src.config import settings


class ReviewOutput(BaseModel):
    approved: bool = Field(description="Whether the fix is correct and safe to merge")
    reasoning: str = Field(description="Explanation of the review decision")
    issues: list[str] = Field(default_factory=list, description="Specific issues found, if any")


REVIEW_PROMPT = """You are a senior code reviewer in an autonomous bug-fixing system.

A failing test was identified, investigated, and a fix was generated and applied in a sandbox.
The fix passed the individual test. Your job is to review the diff for correctness and safety.

## Review criteria
1. **Correctness**: Does the fix actually address the root cause identified in the investigation?
2. **Completeness**: Are all affected files/lines changed? Are there missing changes?
3. **Safety**: Could this fix break other tests or functionality? Are there side effects?
4. **Code quality**: Is the change clean, minimal, and consistent with the codebase style?
5. **Regression risk**: Could this change cause regressions in unrelated code?

## What you'll receive
- The investigation report (root cause, affected files)
- The diff of changes applied in the sandbox
- The original test failure info

## Response
- approved: true if the fix is correct and safe to merge
- approved: false if there are issues that need to be addressed
- reasoning: clear explanation of your decision
- issues: list of specific problems found (empty if approved)
"""


class Reviewer:
    """Reviews code fixes using LLM to ensure correctness and safety."""

    def __init__(self):
        self._model = settings.REVIEW_MODEL
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def review(
        self,
        investigation: dict,
        diff: str,
        bug_id: str,
        test_name: str,
    ) -> Optional[ReviewOutput]:
        """Review a fix diff against the investigation report."""
        messages = [
            {"role": "system", "content": REVIEW_PROMPT},
            {
                "role": "user",
                "content": f"""\
## Bug: {bug_id}
## Test: {test_name}

## Investigation Report
{json.dumps(investigation, indent=2, default=str)}

## Diff of changes applied
{diff}

Review this fix. Is it correct, complete, and safe to merge?""",
            },
        ]

        try:
            response = self._client.beta.chat.completions.parse(
                model=self._model,
                messages=messages,
                response_format=ReviewOutput,
                temperature=0.1,
            )
            return response.choices[0].message.parsed
        except Exception as e:
            print(f"Review failed: {e}")
            return None
