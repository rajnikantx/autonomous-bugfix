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
from src.graph.nodes.review_agent import review_agent
from src.graph.nodes.merge_fix import merge_fix

graph = StateGraph(AgentState)

graph.add_node("clone_project", clone_project)
graph.add_node("scan_bugs", scan_bugs)
graph.add_node("triage", triage)
graph.add_node("select_bug", select_bug)
graph.add_node("investigate", investigate_node)
graph.add_node("generate_fix", generate_fix)
graph.add_node("apply_fix", apply_fix)
graph.add_node("run_tests", run_tests)
graph.add_node("review_agent", review_agent)
graph.add_node("merge_fix", merge_fix)

graph.add_edge(START, "clone_project")
graph.add_edge("clone_project", "scan_bugs")
graph.add_edge("scan_bugs", "triage")
graph.add_edge("triage", "select_bug")


def after_select_bug(state: AgentState) -> str:
    if state.get("active_bug") is not None:
        return "investigate"
    return "end"


graph.add_conditional_edges("select_bug", after_select_bug, {
    "investigate": "investigate",
    "end": END,
})


def after_run_tests(state: AgentState) -> str:
    bug = state.get("active_bug")
    if bug and bug.status == "reviewing":
        return "review"
    return "select"


graph.add_conditional_edges("run_tests", after_run_tests, {
    "review": "review_agent",
    "select": "select_bug",
})


def after_review(state: AgentState) -> str:
    if state.get("review_approved"):
        return "merge"
    return "select"


graph.add_conditional_edges("review_agent", after_review, {
    "merge": "merge_fix",
    "select": "select_bug",
})

graph.add_edge("investigate", "generate_fix")
graph.add_edge("generate_fix", "apply_fix")
graph.add_edge("apply_fix", "run_tests")
graph.add_edge("merge_fix", "select_bug")

workflow = graph.compile()
