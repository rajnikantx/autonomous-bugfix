import subprocess
from copy import deepcopy
from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState, Bug


def _update_bug_in_list(bugs: list[Bug], bug_id: str, updated_bug: Bug) -> list[Bug]:
    new_bugs = deepcopy(bugs)
    for i, b in enumerate(new_bugs):
        if b.bug_id == bug_id:
            new_bugs[i] = updated_bug
            break
    return new_bugs


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
        updated_bug = deepcopy(target_bug)
        updated_bug.status = "escalated"
        new_bugs = _update_bug_in_list(bugs, target_bug.bug_id, updated_bug)
        return {"bugs": new_bugs, "active_bug": None}

    cmd = [
        "python", "-m", "pytest",
        report.test_file,
        "-k", report.test_name,
        "--tb=short",
        "--no-header",
        "-q",
    ]

    logger.info(f"Running test {report.test_name} for {target_bug.bug_id}")
    try:
        result = subprocess.run(
            cmd,
            cwd=sandbox_path,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            updated_bug = deepcopy(target_bug)
            updated_bug.status = "escalated"
            logger.warning(
                f"Bug {target_bug.bug_id} still failing after fix:\n"
                f"{result.stdout}\n{result.stderr}"
            )
            new_bugs = _update_bug_in_list(bugs, target_bug.bug_id, updated_bug)
            return {"bugs": new_bugs, "active_bug": None}

        updated_bug = deepcopy(target_bug)
        updated_bug.status = "reviewing"
        logger.info(f"Bug {target_bug.bug_id} -> reviewing — test passed")

    except Exception as e:
        logger.exception(f"Test run failed for {target_bug.bug_id}")
        updated_bug = deepcopy(target_bug)
        updated_bug.status = "escalated"

    new_bugs = _update_bug_in_list(bugs, target_bug.bug_id, updated_bug)
    return {"bugs": new_bugs, "active_bug": None}
