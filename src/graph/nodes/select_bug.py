from src.graph.states import AgentState


def select_bug(state: AgentState) -> AgentState:
    """
    Select the next pending bug and mark it as investigating.
    """

    bugs = state["bugs"]

    for bug in bugs:
        if bug.status == "pending":
            bug.status = "investigating"
            return {**state, "active_bug": bug}

    return {**state, "active_bug": None}
