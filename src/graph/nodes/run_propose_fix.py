import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState, FixAttempt
from src.agents.fixer import Fixer


def propose_fix(state: AgentState) -> dict:
    """
    Generate a code fix for the current bug based on investigation results.

    Reads affected files, uses LLM to generate a precise fix.
    """
    bug = state.get("current_bug")
    if not bug:
        logger.error("No current_bug set — cannot propose fix")
        return {"error_message": "No current_bug set"}

    sandbox = state.get("sandbox_path")
    if not sandbox or not Path(sandbox).is_dir():
        logger.error(f"Sandbox not found: {sandbox}")
        return {"error_message": f"Sandbox not found: {sandbox}"}

    root_cause = state.get("root_cause", "")
    affected_files = state.get("affected_files", [])
    relevant_snippets = state.get("relevant_snippets", {})

    if not root_cause:
        logger.error("No root_cause — investigate must run first")
        return {"error_message": "No root_cause found. Run investigate first."}

    settings = state.get("settings")
    model = settings.model_name if settings else "gpt-4o"
    api_key = settings.openai_api_key if settings else ""

    logger.info(f"Generating fix for: {bug.test_name}")

    fixer = Fixer(model=model, api_key=api_key)

    try:
        result = fixer.propose_fix(
            bug=bug,
            root_cause=root_cause,
            affected_files=affected_files,
            relevant_snippets=relevant_snippets,
            sandbox=sandbox,
        )
    except Exception as e:
        logger.error(f"Fix generation failed: {e}")
        return {"error_message": f"Fix generation failed: {e}"}

    if not result.old_code or not result.new_code:
        logger.warning("Fix generation returned empty old_code/new_code")
        return {
            "current_fix": FixAttempt(
                file_path=result.file_path,
                old_code="",
                new_code="",
                explanation=result.explanation,
                passed=False,
            )
        }

    logger.success(f"Fix proposed for {result.file_path}")
    logger.info(f"Explanation: {result.explanation}")

    return {
        "current_fix": FixAttempt(
            file_path=result.file_path,
            old_code=result.old_code,
            new_code=result.new_code,
            explanation=result.explanation,
            passed=False,
        ),
        "status": "fixing",
    }
