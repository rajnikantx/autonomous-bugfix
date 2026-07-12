import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState
from src.agents.investigator import Investigator


def investigate(state: AgentState) -> dict:
    """
    Investigate the current bug using a ReAct loop with tools.

    Reads source files, traces call chains, and finds root cause.
    """
    bug = state.get("current_bug")
    if not bug:
        logger.error("No current_bug set — cannot investigate")
        return {"error_message": "No current_bug set"}

    sandbox = state.get("sandbox_path")
    if not sandbox or not Path(sandbox).is_dir():
        logger.error(f"Sandbox not found: {sandbox}")
        return {"error_message": f"Sandbox not found: {sandbox}"}

    settings = state.get("settings")
    model = settings.model_name if settings else "gpt-4o"
    api_key = settings.openai_api_key if settings else ""

    logger.info(f"Investigating: {bug.test_name} in {bug.source_file}")

    investigator = Investigator(model=model, api_key=api_key)

    try:
        result = investigator.investigate(bug, sandbox)
    except Exception as e:
        logger.error(f"Investigation failed: {e}")
        return {"error_message": f"Investigation failed: {e}"}

    logger.success(f"Root cause found: {result.root_cause[:100]}")
    logger.info(f"Affected files: {result.affected_files}")

    return {
        "root_cause": result.root_cause,
        "affected_files": result.affected_files,
        "relevant_snippets": result.relevant_snippets,
        "investigation_steps": result.investigation_steps,
        "status": "investigating",
    }
