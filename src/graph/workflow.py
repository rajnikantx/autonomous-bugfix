from langgraph.graph import StateGraph, START, END

from src.graph.states import AgentState
from src.graph.nodes.clone_project import clone_project
from src.graph.nodes.scan_bugs import scan_bugs
from src.graph.nodes.triage import triage
from src.graph.nodes.select_bug import select_bug
from src.graph.nodes.investigate import investigate_node
from src.graph.nodes.generate_fix import generate_fix
from src.graph.nodes.apply_fix import apply_fix
from src.graph.nodes.run_tests import run_tests

graph = StateGraph(AgentState)


def after_select_bug(state: AgentState) -> str:
    if state.get("active_bug") is not None:
        return "investigate"
    return "end"


def after_investigate(state: AgentState) -> str:
    if state.get("active_bug") is not None:
        return "generate_fix"
    return "select_bug"


def after_apply_fix(state: AgentState) -> str:
    for bug in state.get("bugs", []):
        if bug.status == "pending":
            return "select_bug"
    return "end"


graph.add_node("clone_project", clone_project)
graph.add_node("scan_bugs", scan_bugs)
graph.add_node("triage", triage)
graph.add_node("select_bug", select_bug)
graph.add_node("investigate", investigate_node)
graph.add_node("generate_fix", generate_fix)
graph.add_node("apply_fix", apply_fix)
graph.add_node("run_tests", run_tests)

graph.add_edge(START, "clone_project")
graph.add_edge("clone_project", "scan_bugs")
graph.add_edge("scan_bugs", "triage")
graph.add_edge("triage", "select_bug")
graph.add_conditional_edges("select_bug", after_select_bug, {
    "investigate": "investigate",
    "end": END,
})
graph.add_conditional_edges("investigate", after_investigate, {
    "generate_fix": "generate_fix",
    "select_bug": "select_bug",
})
graph.add_edge("generate_fix", "apply_fix")
graph.add_edge("apply_fix", "run_tests")
graph.add_conditional_edges("run_tests", after_apply_fix, {
    "select_bug": "select_bug",
    "end": END,
})

workflow = graph.compile()
