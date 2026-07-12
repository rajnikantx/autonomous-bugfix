import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState, BugProgress
from src.agents.triage import Triage


def agent_triage(state: AgentState) -> dict:
    bug_report_path = state.get("bug_report_path")

    if not bug_report_path or not Path(bug_report_path).is_file():
        logger.error(f"Bug report not found: {bug_report_path}")
        return {"error_message": f"Bug report not found: {bug_report_path}"}

    logger.info(f"Reading bug report: {bug_report_path}")

    try:
        report_content = Path(bug_report_path).read_text()
    except Exception as e:
        logger.error(f"Failed to read bug report: {e}")
        return {"error_message": f"Failed to read bug report: {e}"}

    if not report_content.strip():
        logger.warning("Bug report is empty")
        return {"error_message": "Bug report is empty"}

    settings = state.get("settings")
    model = settings.model_name if settings else "gpt-4o"
    api_key = settings.openai_api_key if settings else ""
    temperature = settings.temperature if settings else 0.0
    triage = Triage(model=model, api_key=api_key, temperature=temperature)

    logger.info("Sending report to triage agent for analysis")

    try:
        data = triage.get_triage_json(report_content)
    except Exception as e:
        logger.error(f"Triage analysis failed: {e}")
        return {"error_message": f"Triage analysis failed: {e}"}

    bugs = triage.parse_triage_json(data)

    if not bugs:
        logger.warning("Triage returned no bugs")
        return {"pending_bugs": [], "escalated_bugs": [], "bug_progress": {}}

    logger.success(f"Triage complete — found {len(bugs)} bug(s)")

    pending = []
    escalated = []
    progress = {}

    for bug in bugs:
        logger.info(
            f"  [{bug.severity}] {bug.test_name} in {bug.test_file} "
            f"→ {bug.source_file} ({bug.exception_type})"
        )
        if bug.fixable:
            pending.append(bug)
            progress[bug.test_name] = BugProgress(bug=bug, status="pending")
        else:
            escalated.append(bug)
            progress[bug.test_name] = BugProgress(bug=bug, status="escalated")
            logger.warning(f"  Escalated: {bug.escalation_reason or 'marked unfixable'}")

    return {
        "pending_bugs": pending,
        "escalated_bugs": escalated,
        "bug_progress": progress,
    }


if __name__ == "__main__":
    result = agent_triage({"bug_report_path": ".bugfix/pytest_report.json"})
    print(f"\nResult: {result}")
