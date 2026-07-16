import shutil
from copy import deepcopy
from pathlib import Path
from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState, Bug, CodeChange


def _update_bug_in_list(bugs: list[Bug], bug_id: str, updated_bug: Bug) -> list[Bug]:
    new_bugs = deepcopy(bugs)
    for i, b in enumerate(new_bugs):
        if b.bug_id == bug_id:
            new_bugs[i] = updated_bug
            break
    return new_bugs


def _process_merge_output(output):
    bugs = output.get("bugs", [])
    statuses = [b.status for b in bugs]
    return {"bug_count": len(bugs), "statuses": statuses}


@traceable(run_type="chain", name="merge_fix", project_name="autonomous bugfix", process_outputs=_process_merge_output)
def merge_fix(state: AgentState) -> dict:
    """Merges approved fix from sandbox to the actual project."""
    bug = state.get("active_bug")
    pending_fix = state.get("pending_fix")

    if bug is None:
        logger.warning("merge_fix: no active bug")
        return {"bugs": state.get("bugs", []), "active_bug": None}

    if not pending_fix:
        logger.warning(f"merge_fix: no pending fix for {bug.bug_id}")
        updated_bug = deepcopy(bug)
        updated_bug.status = "escalated"
        new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
        return {"bugs": new_bugs, "active_bug": None}

    sandbox_path = state["sandbox_path"]
    repo_path = state["repo_path"]

    try:
        merged = 0
        failed = 0
        for change in pending_fix:
            src = Path(sandbox_path) / change.file_path
            dst = Path(repo_path) / change.file_path

            if not src.exists():
                logger.warning(f"Source file not found in sandbox: {src}")
                failed += 1
                continue

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                merged += 1
                logger.info(f"Merged: {change.file_path} — {change.description}")
            except Exception as e:
                logger.error(f"Failed to merge {change.file_path}: {e}")
                failed += 1

        updated_bug = deepcopy(bug)
        if failed > 0:
            logger.warning(f"{failed}/{merged + failed} files failed to merge for {bug.bug_id}")
            updated_bug.status = "escalated"
        else:
            updated_bug.status = "resolved"
            logger.info(f"Bug {bug.bug_id} resolved — {merged} file(s) merged")

        # Track applied fixes
        existing_fixes = state.get("applied_fixes", [])
        new_applied = existing_fixes + pending_fix

    except Exception as e:
        logger.exception(f"Merge failed for {bug.bug_id}")
        updated_bug = deepcopy(bug)
        updated_bug.status = "escalated"
        new_applied = state.get("applied_fixes", [])

    new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
    return {"bugs": new_bugs, "active_bug": None, "pending_fix": None, "applied_fixes": new_applied}
