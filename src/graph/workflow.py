from langgraph.graph import StateGraph, START, END

from src.graph.states import AgentState
from src.graph.nodes.clone_project import clone_project
from src.graph.nodes.scan_bugs import scan_bugs
from src.graph.nodes.agent_triage import agent_triage
from src.graph.nodes.select_next_bug import select_next_bug
from src.graph.nodes.agent_investigate import agent_investigate
from src.graph.nodes.agent_propose_fix import agent_propose_fix
from src.graph.nodes.agent_review_fix import agent_review_fix
from src.graph.nodes.apply_fix import apply_fix
from src.graph.nodes.agent_test_fix import agent_test_fix
from src.graph.nodes.generate_report import generate_report


def after_select(state: AgentState) -> str:
    if state.get("error_message"):
        return END
    if state.get("current_bug") is None:
        return END
    return "agent_investigate"


def after_review(state: AgentState) -> str:
    if state.get("error_message"):
        return END
    decision = state.get("review_decision", "approve")
    if decision == "reject":
        return "agent_propose_fix"
    return "apply_fix"


def after_test(state: AgentState) -> str:
    if state.get("error_message"):
        return END
    decision = state.get("test_decision", "pass")
    retry_count = state.get("retry_count", 0)
    max_retries = state["settings"].max_retries

    if decision == "pass":
        return "select_next_bug"
    if decision == "retry" and retry_count < max_retries:
        return "agent_propose_fix"
    return END


builder = StateGraph(AgentState)

builder.add_node("clone_project", clone_project)
builder.add_node("scan_bugs", scan_bugs)
builder.add_node("agent_triage", agent_triage)
builder.add_node("select_next_bug", select_next_bug)
builder.add_node("agent_investigate", agent_investigate)
builder.add_node("agent_propose_fix", agent_propose_fix)
builder.add_node("agent_review_fix", agent_review_fix)
builder.add_node("apply_fix", apply_fix)
builder.add_node("agent_test_fix", agent_test_fix)
builder.add_node("generate_report", generate_report)

builder.add_edge(START, "clone_project")
builder.add_edge("clone_project", "scan_bugs")
builder.add_edge("scan_bugs", "agent_triage")
builder.add_edge("agent_triage", "select_next_bug")
builder.add_conditional_edges("select_next_bug", after_select, {
    "agent_investigate": "agent_investigate",
    END: "generate_report",
})
builder.add_edge("agent_investigate", "agent_propose_fix")
builder.add_edge("agent_propose_fix", "agent_review_fix")
builder.add_conditional_edges("agent_review_fix", after_review, {
    "apply_fix": "apply_fix",
    "agent_propose_fix": "agent_propose_fix",
})
builder.add_edge("apply_fix", "agent_test_fix")
builder.add_conditional_edges("agent_test_fix", after_test, {
    "select_next_bug": "select_next_bug",
    "agent_propose_fix": "agent_propose_fix",
    END: "generate_report",
})
builder.add_edge("generate_report", END)

graph = builder.compile()
