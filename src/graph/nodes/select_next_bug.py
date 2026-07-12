import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState


def select_next_bug(state: AgentState) -> dict:
    """
    Pop the next bug from pending_bugs and set it as current_bug.
    If no bugs remain, set current_bug to None.
    """
    pending = state.get("pending_bugs", [])

    if not pending:
        logger.info("No pending bugs left")
        return {"current_bug": None}

    current = pending[0]
    remaining = pending[1:]

    logger.info(
        f"Selected bug: {current.test_name} in {current.test_file} "
        f"({current.severity}) — {len(remaining)} remaining"
    )

    return {
        "current_bug": current,
        "pending_bugs": remaining,
    }
