from copy import deepcopy
from loguru import logger

from src.graph.states import AgentState


def select_bug(state: AgentState) -> AgentState:
    """Select the next pending bug and mark it as investigating."""

    bugs = state["bugs"]

    for bug in bugs:
        if bug.status == "pending":
            updated_bugs = deepcopy(bugs)
            for b in updated_bugs:
                if b.bug_id == bug.bug_id:
                    b.status = "investigating"
                    logger.info(f"active bug: {b.bug_id}")
                    return {**state, "bugs": updated_bugs, "active_bug": b}

    logger.info("active bug: None")
    return {**state, "active_bug": None}
