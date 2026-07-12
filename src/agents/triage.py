from pydantic import BaseModel
from openai import OpenAI
from loguru import logger

from src.graph.states import PytestBug


TRIAGE_SYSTEM = """\
You are an expert bug triage engineer. Your job is to analyze pytest failure reports and extract structured data about each failing test.

## Instructions

1. Read the bug report carefully. Only extract tests with `outcome: "failed"`. Ignore all passing, skipped, or xfailed tests.
2. For each failing test, determine:
   - The test function name and the file it lives in.
   - Which source file likely contains the root cause (it may differ from the test file).
   - A concise summary of the failure (1-2 sentences).
   - The Python exception type (e.g. `ValueError`, `AssertionError`, `KeyError`).
   - Severity based on impact:
     - `high` — core functionality broken, no obvious workaround.
     - `medium` — feature degraded but workaround exists.
     - `low` — edge-case or cosmetic issue.
   - Whether the bug is likely fixable by an automated agent (`true`) or requires human judgment (`false`). Consider it unfixable if the fix requires domain knowledge not present in the report, architectural changes, or external service dependencies.
3. If the report contains a single test failure, still return a one-element array.
4. Do not invent tests or details not present in the report. If a field cannot be determined, use an empty string."""

TRIAGE_USER = """\
## Bug report

{report}"""


class BugReport(BaseModel):
    test_name: str
    test_file: str
    source_file: str
    summary: str
    exception_type: str
    severity: str
    fixable: bool


class TriageResult(BaseModel):
    bugs: list[BugReport]


class Triage:

    def __init__(self, model: str = "gpt-4o", api_key: str = "", temperature: float = 0.0):
        self.model = model
        self.client = OpenAI(api_key=api_key)
        self.temperature = temperature

    def get_triage_json(self, report_content: str) -> list[BugReport]:
        user_prompt = TRIAGE_USER.format(report=report_content)

        logger.info(f"Sending report to {self.model} for analysis")
        response = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": TRIAGE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            response_format=TriageResult,
            temperature=self.temperature,
        )

        result = response.choices[0].message.parsed
        return result.bugs

    def parse_triage_json(self, data: list[BugReport]) -> list[PytestBug]:
        bugs = []
        for item in data:
            bug = PytestBug(
                test_name=item.test_name,
                test_file=item.test_file,
                source_file=item.source_file,
                summary=item.summary,
                exception_type=item.exception_type,
                severity=item.severity,
                traceback=[],
                raw_output="",
                fixable=item.fixable,
            )
            bugs.append(bug)

        return bugs

    def analyze_report(self, report_content: str) -> list[PytestBug]:
        data = self.get_triage_json(report_content)
        return self.parse_triage_json(data)
