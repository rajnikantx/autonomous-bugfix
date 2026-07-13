from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Literal
from loguru import logger
from langsmith import traceable

from src.config import settings

TRIAGE_SYSTEM = """\
You are an expert bug triage engineer. Analyze pytest failure reports and extract structured data.

## Rules

1. Only extract tests with `outcome: "failed"`. Ignore passing, skipped, and xfailed tests.
2. If there are **zero** failing tests, return an empty `bugs` array (`[]`). Do not invent failures.
3. For `traceback`, copy the **raw exception traceback** exactly as it appears in the pytest report. Include everything from the test name header to the last line of the error output. Do not summarize or truncate.
4. Return **strict JSON** matching the provided schema. No markdown, no commentary outside the JSON.

## Severity Guidelines

- `high` — The failure blocks a critical user workflow (e.g., auth, payment, data loss). No workaround.
- `medium` — A feature is broken but users can work around it, or the failure is in a non-critical module.
- `low` — Typo in an error message, cosmetic UI issue, deprecated-API warning treated as error, or extremely rare edge case.

## Fixability Guidelines

- `true` — The fix is a code change within a single file (e.g., wrong variable name, off-by-one error, missing null check, incorrect assertion). The traceback gives enough context.
- `false` — The fix requires: architectural redesign, external API/service changes, security policy decisions, or domain knowledge not present in the report.
"""


TRIAGE_USER = """\
## Pytest Bug Report

{report}

Extract all failing tests as structured JSON.
"""


class BugReport(BaseModel):
    test_name: str = Field(description="Name of the failing test function")
    test_file: str = Field(description="File path where the test lives")
    traceback: str = Field(
        description="The raw, unmodified exception traceback from the pytest report. "
                    "Include everything from the test name header to the last line of the error output."
    )
    summary: str = Field(description="1-2 sentence description of why the test failed")
    exception_type: str = Field(description="Python exception class (e.g., ValueError, AssertionError)")
    severity: Literal["high", "medium", "low"] = Field(description="Impact level: high, medium, or low")
    fixable: bool = Field(description="Whether an AI agent can fix this automatically based on the report alone")


class TriageResult(BaseModel):
    bugs: list[BugReport] = Field(description="List of bugs extracted from the pytest report. Empty array if no failures.")


def _process_triage_output(output):
    if output is None:
        return None
    return {"bugs": [b.model_dump() for b in output.bugs]}


class Triage:
    def __init__(self):
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.TRIAGE_MODEL

    @traceable(run_type="llm", name="triage_llm_call", project_name="autonomous bugfix", process_outputs=_process_triage_output)
    def json_bugs(self, bugreport_content: str) -> TriageResult | None:
        """Extract structured bug reports from pytest output using the OpenAI Responses API.

        Args:
            bugreport_content: Raw pytest failure report text.

        Returns:
            Parsed TriageResult, or None if the LLM call fails.
        """
        logger.info("Extracting structured bug report via OpenAI Responses API")

        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=TRIAGE_SYSTEM,
                input=TRIAGE_USER.format(report=bugreport_content),
                text_format=TriageResult,
            )

            result = response.output_parsed
            if result is None:
                logger.warning("LLM returned empty parsed result")
                return None

            logger.info(f"Extracted {len(result.bugs)} bug(s)")
            return result

        except Exception as e:
            logger.error(f"Failed to extract structured bug report: {e}")
            return None