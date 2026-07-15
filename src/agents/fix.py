import dataclasses
import json
import logging
import os
from typing import List, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from src.config import settings
from src.graph.states import InvestigationResult

logger = logging.getLogger(__name__)


class CodeChange(BaseModel):
    file_path: str = Field(
        ...,
        description="Absolute path to the file to modify. The file must exist in the workspace."
    )
    old_code: str = Field(
        ...,
        description=(
            "The EXACT code snippet to find in the file. Must be a contiguous block "
            "with enough surrounding context (3-5 lines) to be unique. Character-for-character "
            "match required — the harness will reject the patch if this is not found literally."
        )
    )
    new_code: str = Field(
        ...,
        description=(
            "The replacement code snippet. Should maintain consistent indentation and style "
            "with the surrounding code. All changes across files must be mutually consistent."
        )
    )
    description: str = Field(
        ...,
        description="One-sentence explanation of why this specific change fixes the bug."
    )


class FixOutput(BaseModel):
    changes: List[CodeChange] = Field(
        ...,
        description=(
            "Ordered list of code changes to apply. Each change is a search-and-replace "
            "operation. The harness applies all changes atomically — if any change fails "
            "validation, the entire patch is rejected and rolled back."
        )
    )


class EditPlanStep(BaseModel):
    index: int = Field(..., description="Step order index")
    file_path: str = Field(..., description="File to modify")
    description: str = Field(..., description="What to change and why")
    depends_on: List[int] = Field(default_factory=list, description="Indices of steps that must complete before this one")
    constraint: Optional[str] = Field(None, description="Special constraints, e.g., 'sync context, cannot use await'")


class EditPlan(BaseModel):
    reasoning: str = Field(..., description="Why the changes must happen in this order")
    edits: List[EditPlanStep] = Field(..., description="Ordered list of planned edits")


PLANNER = """You are a senior software engineer planning a bug fix.
Given a list of investigation findings, produce an ordered, minimal-risk plan of the
edits needed to fix the reported bugs. Do not write code yet: decide which files need
to change, in what order, why that order matters, and any constraints the implementer
must respect (e.g. sync vs async context, existing function signatures)."""

REPLANNER = """You are a senior software engineer revising a bug-fix plan.
One step of a previous plan referenced code that could not be found verbatim in the
target file, which means the assumption behind that step was wrong. Given the original
report, the original plan, and the step that failed, produce a corrected step for that
file. Do not assume the rest of the plan is wrong unless the report implies otherwise."""

GENERATOR = """You are a senior software engineer implementing an approved bug-fix plan.
Given the investigation report and the plan, produce exact search-and-replace code
changes. Every old_code value must be copied verbatim from the real file content, with
enough surrounding context to be unique, and every new_code value must be consistent
with the other changes in the patch."""


class Fixer:
    """Plans and generates code patches for bugs surfaced by an investigation step.

    Flow: _plan() produces an EditPlan -> _generate() turns that plan into concrete
    CodeChanges -> fix() validates each old_code snippet actually exists in its file
    before letting the patch through, replanning the specific steps that don't.
    """

    MAX_REPLAN_ATTEMPTS = 3

    def __init__(self):
        self._model = settings.FIX_MODEL
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

    @staticmethod
    def _serialize_report(report: List[InvestigationResult]) -> str:
        """Best-effort JSON serialization. Works whether InvestigationResult is a
        pydantic BaseModel or a plain dict/TypedDict."""
        try:
            return json.dumps([
                dataclasses.asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
                for item in report
            ], indent=2, default=str)
        except Exception:
            return str(report)

    def _plan(self, report: List[InvestigationResult]) -> Optional[EditPlan]:
        messages = [
            {"role": "system", "content": PLANNER},
            {"role": "user", "content": f"Fix the following bugs:\n{self._serialize_report(report)}"},
        ]
        try:
            response = self._client.chat.completions.parse(
                model=self._model,
                messages=messages,
                response_format=EditPlan,
                temperature=0.3,
            )
            message = response.choices[0].message
            if message.refusal:
                logger.error("Planner refused: %s", message.refusal)
                return None
            return message.parsed
        except Exception:
            logger.exception("Fixer._plan failed")
            return None

    def _replan(
        self,
        report: List[InvestigationResult],
        previous_plan: EditPlan,
        failed_step: EditPlanStep,
    ) -> Optional[EditPlan]:
        messages = [
            {"role": "system", "content": REPLANNER},
            {
                "role": "user",
                "content": (
                    f"Original report:\n{self._serialize_report(report)}\n\n"
                    f"Original plan:\n{previous_plan.model_dump_json(indent=2)}\n\n"
                    f"Step that failed validation (old_code not found in file):\n"
                    f"{failed_step.model_dump_json(indent=2)}\n\n"
                    "Return a corrected full plan."
                ),
            },
        ]
        try:
            response = self._client.chat.completions.parse(
                model=self._model,
                messages=messages,
                response_format=EditPlan,
                temperature=0.3,
            )
            message = response.choices[0].message
            if message.refusal:
                logger.error("Replanner refused: %s", message.refusal)
                return None
            return message.parsed
        except Exception:
            logger.exception("Fixer._replan failed")
            return None

    def _generate(self, plan: EditPlan, report: List[InvestigationResult]) -> Optional[FixOutput]:
        messages = [
            {"role": "system", "content": GENERATOR},
            {
                "role": "user",
                "content": (
                    f"Report:\n{self._serialize_report(report)}\n\n"
                    f"Plan:\n{plan.model_dump_json(indent=2)}"
                ),
            },
        ]
        try:
            response = self._client.chat.completions.parse(
                model=self._model,
                messages=messages,
                response_format=FixOutput,
                temperature=0.3,
            )
            message = response.choices[0].message
            if message.refusal:
                logger.error("Generator refused: %s", message.refusal)
                return None
            return message.parsed
        except Exception:
            logger.exception("Fixer._generate failed")
            return None

    @staticmethod
    def _old_code_exists(file_path: str, old_code: str) -> bool:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return old_code in f.read()
        except OSError:
            logger.warning("Could not read %s while validating a patch", file_path)
            return False

    def fix(self, report: List[InvestigationResult], sandbox_path: Optional[str] = None) -> Optional[FixOutput]:
        """Plan, generate, and validate a patch. If any change's old_code can't be
        found verbatim in its target file, replan just the offending step(s) and
        regenerate, up to MAX_REPLAN_ATTEMPTS times."""
        plan = self._plan(report)
        if plan is None:
            logger.error("Fixer.fix: initial planning failed")
            return None

        for attempt in range(1, self.MAX_REPLAN_ATTEMPTS + 1):
            output = self._generate(plan, report)
            if output is None:
                logger.error("Fixer.fix: generation failed on attempt %d", attempt)
                return None

            missing = []
            for change in output.changes:
                check_path = change.file_path
                if sandbox_path and not os.path.isabs(check_path):
                    check_path = os.path.join(sandbox_path, check_path)
                if not self._old_code_exists(check_path, change.old_code):
                    missing.append(change)

            if not missing:
                return output

            if attempt == self.MAX_REPLAN_ATTEMPTS:
                break

            bad_files = {change.file_path for change in missing}
            logger.info(
                "Attempt %d: old_code not found for %s, replanning",
                attempt, sorted(bad_files),
            )
            for step in plan.edits:
                if step.file_path in bad_files:
                    revised = self._replan(report, plan, step)
                    if revised is not None:
                        plan = revised

        logger.error(
            "Fixer.fix: exceeded %d replan attempts, giving up",
            self.MAX_REPLAN_ATTEMPTS,
        )
        return None