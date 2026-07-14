from langgraph.graph import StateGraph, START, END

from src.graph.states import AgentState
from src.graph.nodes.clone_project import clone_project
from src.graph.nodes.scan_bugs import scan_bugs
from src.graph.nodes.triage import triage
from src.graph.nodes.select_bug import select_bug
from src.graph.nodes.investigate import investigate_node

graph = StateGraph(AgentState)


def has_active_bug(state: AgentState) -> str | None:
    if state.get("active_bug") is None:
        return None
    return "investigate"


graph.add_node("clone_project", clone_project)
graph.add_node("scan_bugs", scan_bugs)
graph.add_node("triage", triage)
graph.add_node("select_bug", select_bug)
graph.add_node("investigate", investigate_node)

graph.add_edge(START, "clone_project")
graph.add_edge("clone_project", "scan_bugs")
graph.add_edge("scan_bugs", "triage")
graph.add_edge("triage", "select_bug")
graph.add_conditional_edges("select_bug", has_active_bug, {
    "investigate": "investigate",
    None: END,
})
graph.add_edge("investigate", END)

workflow = graph.compile()
