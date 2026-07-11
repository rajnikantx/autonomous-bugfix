import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState
from src.agents.triage import Triage


def run_triage(state: AgentState) -> dict:
    """
    Analyze the pytest report and extract structured bug data.

    1. Read the pytest JSON report from disk.
    2. Send it to the Triage agent for analysis.
    3. Populate pytest_bugs and pending_bugs in state.
    """
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
    triage = Triage(model=model, api_key=api_key)

    logger.info("Sending report to triage agent for analysis")

    try:
        data = triage.get_triage_json(report_content)
    except Exception as e:
        logger.error(f"Triage analysis failed: {e}")
        return {"error_message": f"Triage analysis failed: {e}"}

    bugs = triage.parse_triage_json(data)

    if not bugs:
        logger.warning("Triage returned no bugs")
        return {"pytest_bugs": [], "pending_bugs": []}

    logger.success(f"Triage complete — found {len(bugs)} bug(s)")

    for bug in bugs:
        logger.info(
            f"  [{bug.severity}] {bug.test_name} in {bug.test_file} "
            f"→ {bug.source_file} ({bug.exception_type})"
        )

    return {
        "pytest_bugs": list(bugs),
        "pending_bugs": list(bugs),
    }


if __name__ == "__main__":
    result = run_triage({"bug_report_path": ".bugfix/pytest_report.json"})
    print(f"\nResult: {result}")