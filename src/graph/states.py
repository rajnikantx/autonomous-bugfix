from typing import TypedDict, Literal
from dataclasses import dataclass


@dataclass
class FailureReport:
    test_name: str
    test_file: str
    traceback: str
    failure_summary: str
    exception_type: str
    severity: Literal["high", "medium", "low"]
    auto_fixable: bool

@dataclass
class Bug:
    bug_id: str
    status: Literal[
        "pending", "investigating", "patching", "testing",
        "reviewing", "resolved", "escalated", "wontfix", "rejected"
    ] = "pending"
    report: FailureReport | None = None

class AgentState(TypedDict):
    repo_path: str
    sandbox_path: str
    bugreport_path: str

    bugs: list[Bug]