import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState
from src.agents.tester import Tester


def agent_test_fix(state: AgentState) -> dict:
    bug = state.get("current_bug")
    if not bug:
        logger.error("No current_bug set — cannot test fix")
        return {"error_message": "No current_bug set"}

    sandbox = state.get("sandbox_path")
    if not sandbox or not Path(sandbox).is_dir():
        logger.error(f"Sandbox not found: {sandbox}")
        return {"error_message": f"Sandbox not found: {sandbox}"}

    settings = state.get("settings")
    model = settings.model_name if settings else "gpt-4o"
    api_key = settings.openai_api_key if settings else ""
    temperature = settings.temperature if settings else 0.0

    logger.info(f"Testing fix for: {bug.test_name}")

    tester = Tester(model=model, api_key=api_key, temperature=temperature)

    try:
        result = tester.run_and_analyze(sandbox=sandbox, bug_test_name=bug.test_name)
    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        return {"error_message": f"Test execution failed: {e}"}

    retry_count = state.get("retry_count", 0)
    if result.decision == "retry":
        retry_count += 1
    elif result.decision in ("pass", "escalate"):
        retry_count = 0

    progress = dict(state.get("bug_progress", {}))
    key = bug.test_name
    if key in progress:
        progress[key].test_history.append({
            "decision": result.decision,
            "output": result.test_output_excerpt,
        })
        progress[key].status = "testing"

    return {
        "test_decision": result.decision,
        "test_output": result.test_output_excerpt,
        "retry_count": retry_count,
        "status": "testing",
        "bug_progress": progress,
    }
