from langgraph.graph import StateGraph, START, END

from src.graph.states import AgentState
from src.graph.nodes.clone_project import clone_project
from src.graph.nodes.scan_bugs import scan_bugs


builder = StateGraph(AgentState)

builder.add_node("clone_project", clone_project)
builder.add_node("scan_bugs", scan_bugs)

builder.add_edge(START, "clone_project")
builder.add_edge("clone_project", "scan_bugs")
builder.add_edge("scan_bugs", END)

graph = builder.compile()
