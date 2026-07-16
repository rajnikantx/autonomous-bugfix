import json
import subprocess
from copy import deepcopy
from pathlib import Path
from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState, Bug
from src.agents.review import Reviewer


def _update_bug_in_list(bugs: list[Bug], bug_id: str, updated_bug: Bug) -> list[Bug]:
    new_bugs = deepcopy(bugs)
    for i, b in enumerate(new_bugs):
        if b.bug_id == bug_id:
            new_bugs[i] = updated_bug
            break
    return new_bugs


def _get_sandbox_diff(sandbox_path: str, repo_path: str, changed_files: list[str]) -> str:
    """Generate diff between sandbox and original repo for changed files."""
    diffs = []
    for file_path in changed_files:
        sandbox_file = Path(sandbox_path) / file_path
        repo_file = Path(repo_path) / file_path

        if not repo_file.exists():
            diffs.append(f"--- {file_path} (new file)\n+++ {file_path}\n{sandbox_file.read_text(encoding='utf-8')}")
            continue

        try:
            result = subprocess.run(
                ["diff", "-u", str(repo_file), str(sandbox_file)],
                capture_output=True, text=True
            )
            if result.stdout:
                diffs.append(result.stdout)
        except Exception as e:
            diffs.append(f"--- {file_path}\n+++ (diff failed: {e})")

    return "\n".join(diffs) if diffs else "(no differences found)"


def _process_review_output(output):
    bugs = output.get("bugs", [])
    statuses = [b.status for b in bugs]
    return {"bug_count": len(bugs), "statuses": statuses}


@traceable(run_type="chain", name="review_agent", project_name="autonomous bugfix", process_outputs=_process_review_output)
def review_agent(state: AgentState) -> dict:
    """Reviews the diff of applied fixes using LLM."""
    bug = state.get("active_bug")

    if bug is None:
        logger.warning("review_agent: no active bug")
        return {"bugs": state.get("bugs", []), "active_bug": None}

    if bug.status != "reviewing":
        logger.warning(f"review_agent: bug {bug.bug_id} status is {bug.status}, expected reviewing")
        updated_bug = deepcopy(bug)
        updated_bug.status = "escalated"
        new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
        return {"bugs": new_bugs, "active_bug": None}

    pending_fix = state.get("pending_fix")
    if not pending_fix:
        logger.warning(f"review_agent: no pending fix for {bug.bug_id}")
        updated_bug = deepcopy(bug)
        updated_bug.status = "escalated"
        new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
        return {"bugs": new_bugs, "active_bug": None}

    sandbox_path = state["sandbox_path"]
    repo_path = state["repo_path"]

    try:
        changed_files = [c.file_path for c in pending_fix]
        diff = _get_sandbox_diff(sandbox_path, repo_path, changed_files)

        investigation_dict = {}
        if bug.investigation:
            from dataclasses import asdict
            investigation_dict = asdict(bug.investigation)

        reviewer = Reviewer()
        review_result = reviewer.review(
            investigation=investigation_dict,
            diff=diff,
            bug_id=bug.bug_id,
            test_name=bug.report.test_name if bug.report else "unknown",
        )

        if review_result is None:
            logger.error(f"Review failed for {bug.bug_id}")
            updated_bug = deepcopy(bug)
            updated_bug.status = "escalated"
            new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
            return {"bugs": new_bugs, "active_bug": None, "review_approved": False}

        if review_result.approved:
            logger.info(f"Bug {bug.bug_id} review approved: {review_result.reasoning}")
            return {"bugs": state["bugs"], "active_bug": bug, "review_approved": True}
        else:
            logger.warning(f"Bug {bug.bug_id} review rejected: {review_result.reasoning}")
            logger.warning(f"Issues: {review_result.issues}")
            updated_bug = deepcopy(bug)
            updated_bug.status = "escalated"
            new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
            return {"bugs": new_bugs, "active_bug": None, "review_approved": False}

    except Exception as e:
        logger.exception(f"Review failed for {bug.bug_id}")
        updated_bug = deepcopy(bug)
        updated_bug.status = "escalated"
        new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
        return {"bugs": new_bugs, "active_bug": None, "review_approved": False}
