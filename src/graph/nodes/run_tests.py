import subprocess
from pathlib import Path
from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState
from src.step_logger import save_step_output


def _process_run_tests_output(output):
    bugs = output.get("bugs", [])
    statuses = [b.status for b in bugs]
    return {"bug_count": len(bugs), "statuses": statuses}


@traceable(run_type="chain", name="run_tests", project_name="autonomous bugfix", process_outputs=_process_run_tests_output)
def run_tests(state: AgentState) -> dict:
    """Run the failing test for the most recently fixed bug and update status."""
    sandbox_path = state["sandbox_path"]
    bugs = state.get("bugs", [])

    active_bug = state.get("active_bug")
    target_bug = active_bug

    if target_bug is None:
        # Look for a bug in testing status
        for bug in bugs:
            if bug.status == "testing":
                target_bug = bug
                break

    if target_bug is None:
        logger.info("run_tests: no bug in testing status to verify")
        return {"bugs": bugs, "active_bug": None}

    report = target_bug.report
    if report is None:
        logger.warning(f"Bug {target_bug.bug_id} has no report")
        target_bug.status = "escalated"
        return {"bugs": bugs, "active_bug": None}

    cmd = [
        "python", "-m", "pytest",
        report.test_file,
        "-k", report.test_name,
        "--tb=short",
        "--no-header",
        "-q",
    ]

    logger.info(f"Running tests for {target_bug.bug_id}")
    try:
        result = subprocess.run(
            cmd,
            cwd=sandbox_path,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            target_bug.status = "resolved"
            logger.info(f"Bug {target_bug.bug_id} resolved")
        else:
            target_bug.status = "escalated"
            logger.warning(
                f"Bug {target_bug.bug_id} still failing after fix:\n"
                f"{result.stdout}\n{result.stderr}"
            )
    except Exception as e:
        logger.exception(f"Test run failed for {target_bug.bug_id}")
        target_bug.status = "escalated"

    save_step_output(state["session_id"], "run_tests", {
        "bug_id": target_bug.bug_id,
        "status": target_bug.status,
    })

    return {"bugs": bugs, "active_bug": None}
