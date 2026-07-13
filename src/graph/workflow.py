from langgraph.graph import StateGraph, START, END
from src.graph.states import AgentState
from src.graph.nodes.clone_project import clone_project

graph = StateGraph(AgentState)

graph.add_node("clone_project", clone_project)

graph.add_edge(START, "clone_project")
graph.add_edge("clone_project", END)

workflow = graph.compile()
