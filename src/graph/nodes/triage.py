import json
import uuid
from pathlib import Path
from loguru import logger
from langsmith import traceable
from dataclasses import asdict

from src.graph.states import AgentState, FailureReport, Bug
from src.agents.triage import Triage


def _process_triage_output(output):
    bugs = output.get("bugs", [])
    return {"bug_count": len(bugs)}

@traceable(run_type="chain", name="triage", project_name="autonomous bugfix", process_outputs=_process_triage_output)
def triage(state: AgentState):
    """
    Read the pytest JSON report, pass it through the Triage agent,
    and convert the results into Bugs.
    """
    bugreport_path = Path(state["bugreport_path"])

    if not bugreport_path.is_file():
        logger.error(f"Bug report not found: {bugreport_path}")
        return {
            **state, 
            "bugs": []
        }

    report_content = bugreport_path.read_text()

    agent = Triage()
    result = agent.json_bugs(report_content)

    if result is None or not result.bugs:
        logger.info("No failing tests found in the report")
        return {
            **state, 
            "bugs": []
        }

    bugs = []
    for bug_report in result.bugs:
        report = FailureReport(
            test_name=bug_report.test_name,
            test_file=bug_report.test_file,
            traceback=bug_report.traceback,
            failure_summary=bug_report.summary,
            exception_type=bug_report.exception_type,
            severity=bug_report.severity,
            auto_fixable=bug_report.fixable,
        )

        bug = Bug(
            bug_id=f"{report.test_name} :: {report.test_file}",
            status="pending",
            report=report,
        )
        bugs.append(bug)

    logger.info(f"Created {len(bugs)} bug(s)")

    triage_output_path = "logs/triage_output"
    logger.debug(f"triage output logged at {triage_output_path}")

    output_data = {
        **state,
        "bugs": [asdict(b) for b in bugs]
    }
    with open(triage_output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)

    return {
        **state, 
        "bugs": bugs
    }
