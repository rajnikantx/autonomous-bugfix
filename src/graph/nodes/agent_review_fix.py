import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState
from src.agents.reviewer import Reviewer


def agent_review_fix(state: AgentState) -> dict:
    bug = state.get("current_bug")
    if not bug:
        logger.error("No current_bug set — cannot review fix")
        return {"error_message": "No current_bug set"}

    current_fix = state.get("current_fix")
    if not current_fix:
        logger.error("No current_fix set — cannot review fix")
        return {"error_message": "No current_fix set"}

    sandbox = state.get("sandbox_path")
    if not sandbox or not Path(sandbox).is_dir():
        logger.error(f"Sandbox not found: {sandbox}")
        return {"error_message": f"Sandbox not found: {sandbox}"}

    root_cause = state.get("root_cause", "")

    settings = state.get("settings")
    model = settings.model_name if settings else "gpt-4o"
    api_key = settings.openai_api_key if settings else ""
    temperature = settings.temperature if settings else 0.0

    logger.info(f"Reviewing fix for: {bug.test_name}")

    reviewer = Reviewer(model=model, api_key=api_key, temperature=temperature)

    try:
        result = reviewer.review(
            fix=current_fix,
            root_cause=root_cause,
            sandbox=sandbox,
        )
    except Exception as e:
        logger.error(f"Review failed: {e}")
        return {"error_message": f"Review failed: {e}"}

    logger.info(f"Review decision: {result.decision}")

    if result.objections:
        for obj in result.objections:
            logger.warning(f"  Objection: {obj}")

    progress = dict(state.get("bug_progress", {}))
    key = bug.test_name
    if key in progress:
        progress[key].review_history.append({
            "decision": result.decision,
            "objections": result.objections,
        })
        progress[key].status = "reviewing"

    return {
        "review_decision": result.decision,
        "review_objections": result.objections,
        "status": "reviewing",
        "bug_progress": progress,
    }
