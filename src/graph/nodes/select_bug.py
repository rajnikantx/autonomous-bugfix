from loguru import logger

from src.graph.states import AgentState
from src.step_logger import save_step_output


def select_bug(state: AgentState) -> AgentState:
    """
    Select the next pending bug and mark it as investigating.
    """

    bugs = state["bugs"]

    for bug in bugs:
        if bug.status == "pending":
            bug.status = "investigating"
            logger.info(f"Selected bug: {bug.bug_id}")

            save_step_output(state["session_id"], "select_bug", {
                "selected_bug_id": bug.bug_id,
                "status": bug.status,
            })

            return {**state, "active_bug": bug}

    return {**state, "active_bug": None}
