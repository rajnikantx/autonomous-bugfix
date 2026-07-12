from __future__ import annotations

import json
from pydantic import BaseModel
from openai import OpenAI
from loguru import logger

from src.tools.sandbox import run_pytest_in_sandbox, install_dependencies


TEST_SYSTEM = """\
You are an expert test analyst. You run tests against a proposed fix and decide what happens next.

## Process

1. You will receive the raw output from running pytest.
2. Analyze the results carefully.
3. Decide one of three outcomes:

   a) **pass** — The originally failing test now passes AND no new tests failed. The fix is good.
   b) **retry** — The fix didn't work, but you can see what went wrong. The Fix Agent should try again with this new information.
   c) **escalate** — The fix made things worse, or the problem is too complex for automated fixing. Needs human review.

## Decision criteria

- If the originally failing test passes and no new failures → **pass**
- If the originally failing test still fails but the error changed → **retry** (the fix was partially right)
- If new tests failed that weren't failing before → **escalate** (fix introduced regressions)
- If the test output shows a completely different error → **retry** (wrong diagnosis)
- If the error is in a different domain than what the fix addressed → **escalate**

## Output

Output ONLY a JSON object:
```json
{
  "decision": "pass | retry | escalate",
  "summary": "Brief explanation of what happened",
  "test_output_excerpt": "Relevant excerpt from test output (keep under 500 chars)",
  "reasoning": "Why you made this decision"
}
```
No markdown fences. No other text. Just the JSON."""


class TestResult(BaseModel):
    decision: str
    summary: str
    test_output_excerpt: str
    reasoning: str


class Tester:

    def __init__(self, model: str = "gpt-4o", api_key: str = "", temperature: float = 0.0):
        self.model = model
        self.client = OpenAI(api_key=api_key)
        self.temperature = temperature

    def run_and_analyze(self, sandbox: str, bug_test_name: str = "") -> TestResult:
        logger.info("Installing dependencies in sandbox")
        install_dependencies(sandbox)

        logger.info("Running pytest in sandbox")
        pytest_result = run_pytest_in_sandbox(sandbox)

        if pytest_result.raw_output.startswith("ERROR"):
            logger.error(f"Pytest execution error: {pytest_result.raw_output}")
            return TestResult(
                decision="escalate",
                summary="Pytest execution failed",
                test_output_excerpt=pytest_result.raw_output[:500],
                reasoning=f"Could not run tests: {pytest_result.raw_output}",
            )

        logger.info(
            f"Test results: {pytest_result.num_passed} passed, "
            f"{pytest_result.num_failed} failed, {pytest_result.num_errors} errors"
        )

        messages = [
            {"role": "system", "content": TEST_SYSTEM},
            {"role": "user", "content": self._build_analysis_message(pytest_result, bug_test_name)},
        ]

        logger.info("Analyzing test results with LLM")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )

        content = response.choices[0].message.content

        try:
            result = TestResult.model_validate_json(content)
        except Exception:
            try:
                data = json.loads(content)
                result = TestResult(**data)
            except Exception as e:
                logger.error(f"Failed to parse test analysis: {e}")
                result = TestResult(
                    decision="retry",
                    summary="Test analysis parse failed",
                    test_output_excerpt=pytest_result.raw_output[:500],
                    reasoning=f"Could not parse LLM response: {e}",
                )

        logger.info(f"Test decision: {result.decision} — {result.summary}")
        return result

    def _build_analysis_message(self, pytest_result, bug_test_name: str) -> str:
        parts = [
            "## Test execution results",
            f"Total: {pytest_result.total}",
            f"Passed: {pytest_result.num_passed}",
            f"Failed: {pytest_result.num_failed}",
            f"Errors: {pytest_result.num_errors}",
        ]

        if pytest_result.failing_tests:
            parts.append(f"\nFailing tests: {', '.join(pytest_result.failing_tests)}")

        if bug_test_name:
            parts.append(f"\nOriginally failing test: {bug_test_name}")
            if bug_test_name in pytest_result.failing_tests:
                parts.append("STATUS: Still failing")
            else:
                parts.append("STATUS: Now passing ✓")

        parts.append(f"\n## Raw test output\n```\n{pytest_result.raw_output[:3000]}\n```")

        parts.append(
            "\nAnalyze these results. Decide: pass, retry, or escalate. Output JSON."
        )

        return "\n".join(parts)
