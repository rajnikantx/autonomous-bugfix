import subprocess
from pathlib import Path
from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState

BUG_REPORT_DIR= "bug_report"
PYTEST_BUGREPORT_FILE= "pytest_bugreport.json"


def _process_scan_output(output):
    return {"bugreport_path": str(output.get("bugreport_path", ""))}


@traceable(run_type="chain", name="scan_bugs", project_name="autonomous bugfix", process_outputs=_process_scan_output)
def scan_bugs(state: AgentState):
    """
    run pytest command to get the bug report for pytest.
    """
    sandbox_path= state["sandbox_path"]
    bugreport_dir= Path(sandbox_path) / BUG_REPORT_DIR
    bugreport_dir.mkdir(exist_ok=True)
    bugreport_path= Path(bugreport_dir) / PYTEST_BUGREPORT_FILE

    cmd = [
        "pytest",
        "--json-report",
        f"--json-report-file={bugreport_path}",
        "--verbose",
        "--tb=short",
        "--no-header",
    ]

    logger.info(f"generating pytest bug report at : {bugreport_path}")
    try:
        bugs= subprocess.run(
            cmd, 
            cwd=sandbox_path,
            capture_output=True,
            text=True
        )

        if bugs.returncode != 0:
            logger.error(f"Tests failed")
        logger.info(f"pytest bug report generated at {bugreport_path}")

    except Exception as e:
        logger.exception(f"failed pytest bug report generation for {sandbox_path}")


    return {
        **state,
        "bugreport_path": str(bugreport_path)
    }