import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState


def select_next_bug(state: AgentState) -> dict:
    current_bug = state.get("current_bug")
    test_decision = state.get("test_decision", "")
    pending = state.get("pending_bugs", [])
    fixed = list(state.get("fixed_bugs", []))
    failed = list(state.get("failed_bugs", []))
    progress = dict(state.get("bug_progress", {}))

    if current_bug:
        key = current_bug.test_name
        if test_decision == "pass":
            fixed.append(current_bug)
            if key in progress:
                progress[key].status = "done"
            logger.info(f"Bug {key} marked as FIXED")
        elif test_decision == "escalate":
            failed.append(current_bug)
            if key in progress:
                progress[key].status = "failed"
            logger.info(f"Bug {key} marked as FAILED")

    if not pending:
        logger.info("No pending bugs left")
        return {"current_bug": None, "current_bug_key": "", "fixed_bugs": fixed, "failed_bugs": failed, "bug_progress": progress}

    current = pending[0]
    remaining = pending[1:]

    if current.test_name in progress:
        progress[current.test_name].status = "investigating"

    logger.info(
        f"Selected bug: {current.test_name} in {current.test_file} "
        f"({current.severity}) — {len(remaining)} remaining"
    )

    return {
        "current_bug": current,
        "current_bug_key": current.test_name,
        "pending_bugs": remaining,
        "fixed_bugs": fixed,
        "failed_bugs": failed,
        "bug_progress": progress,
    }
