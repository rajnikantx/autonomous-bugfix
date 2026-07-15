from pathlib import Path
from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState
from src.tools.file_ops import apply_patch
from src.step_logger import save_step_output


def _process_apply_fix_output(output):
    bugs = output.get("bugs", [])
    statuses = [b.status for b in bugs]
    return {"bug_count": len(bugs), "statuses": statuses}


@traceable(run_type="chain", name="apply_fix", project_name="autonomous bugfix", process_outputs=_process_apply_fix_output)
def apply_fix(state: AgentState) -> dict:
    """Applies the pending fix patches to the sandbox."""
    bug = state.get("active_bug")
    pending_fix = state.get("pending_fix")

    if bug is None:
        logger.warning("apply_fix: no active bug")
        return {"bugs": state.get("bugs", []), "active_bug": None}

    if not pending_fix:
        logger.warning(f"apply_fix: no pending fix for {bug.bug_id}")
        bug.status = "escalated"
        save_step_output(state["session_id"], "apply_fix", {
            "bug_id": bug.bug_id,
            "status": bug.status,
        })
        return {"bugs": state["bugs"], "active_bug": None}

    sandbox_path = state["sandbox_path"]

    try:
        applied = 0
        failed = 0
        for change in pending_fix:
            path = Path(change.file_path)
            if not path.is_absolute():
                path = Path(sandbox_path) / path
            abs_path = str(path)
            success = apply_patch(abs_path, change.old_code, change.new_code)
            if success:
                applied += 1
                logger.info(f"Applied: {change.file_path} — {change.description}")
            else:
                failed += 1
                logger.error(f"Failed to apply: {change.file_path} — {change.description}")

        if failed > 0:
            logger.warning(f"{failed}/{applied + failed} patches failed for {bug.bug_id}")
            bug.status = "escalated"
        else:
            bug.status = "testing"
            logger.info(
                f"Bug {bug.bug_id} -> testing. "
                f"Applied {applied} change(s)."
            )

    except Exception as e:
        logger.exception(f"Fix application failed for {bug.bug_id}")
        bug.status = "escalated"

    save_step_output(state["session_id"], "apply_fix", {
        "bug_id": bug.bug_id,
        "status": bug.status,
    })

    return {"bugs": state["bugs"], "active_bug": None, "pending_fix": None}
