from langgraph.graph import StateGraph, START, END

from src.graph.states import AgentState
from src.graph.nodes.clone_project import clone_project
from src.graph.nodes.scan_bugs import scan_bugs
from src.graph.nodes.triage import triage


def _build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("clone_project", clone_project)
    graph.add_node("scan_bugs", scan_bugs)
    graph.add_node("triage", triage)

    graph.add_edge(START, "clone_project")
    graph.add_edge("clone_project", "scan_bugs")
    graph.add_edge("scan_bugs", "triage")
    graph.add_edge("triage", END)

    return graph


workflow = _build_graph().compile()
