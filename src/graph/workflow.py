from langgraph.graph import StateGraph, START, END

from src.graph.states import AgentState
from src.graph.nodes.clone_project import clone_project


builder = StateGraph(AgentState)

builder.add_node("clone_project", clone_project)

builder.add_edge(START, "clone_project")
builder.add_edge("clone_project", END)

graph = builder.compile()
