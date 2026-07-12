from langgraph.graph import StateGraph, START, END

from src.graph.states import AgentState
from src.graph.nodes.clone_project import clone_project
from src.graph.nodes.scan_bugs import scan_bugs
from src.graph.nodes.run_triage import run_triage
from src.graph.nodes.select_next_bug import select_next_bug
from src.graph.nodes.run_investigate import investigate
from src.graph.nodes.run_propose_fix import propose_fix
from graph.nodes.apply_fix import apply_fix


builder = StateGraph(AgentState)

builder.add_node("clone_project", clone_project)
builder.add_node("scan_bugs", scan_bugs)
builder.add_node("run_triage", run_triage)
builder.add_node("select_next_bug", select_next_bug)
builder.add_node("investigate", investigate)
builder.add_node("propose_fix", propose_fix)
builder.add_node("apply_fix", apply_fix)

builder.add_edge(START, "clone_project")
builder.add_edge("clone_project", "scan_bugs")
builder.add_edge("scan_bugs", "run_triage")
builder.add_edge("run_triage", "select_next_bug")
builder.add_edge("select_next_bug", "investigate")
builder.add_edge("investigate", "propose_fix")
builder.add_edge("propose_fix", "apply_fix")
builder.add_edge("apply_fix", END)

graph = builder.compile()
