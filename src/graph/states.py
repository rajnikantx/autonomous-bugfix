from typing import TypedDict, Literal
from dataclasses import dataclass, field


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
class InvestigationResult:
    bug_id: str
    test_name: str
    root_cause: str
    affected_files: list[str]
    affected_lines: dict[str, list[int]]
    affected_functions: list[str] = field(default_factory=list)
    affected_classes: list[str] = field(default_factory=list)
    code_snippets: dict[str, str] = field(default_factory=dict)
    file_reasoning: dict[str, str] = field(default_factory=dict)
    confidence: Literal["high", "medium", "low"] = "low"
    reasoning_trace: list[str] = field(default_factory=list)

@dataclass
class CodeChange:
    file_path: str
    old_code: str
    new_code: str
    description: str


@dataclass
class Bug:
    bug_id: str
    status: Literal[
        "pending", "investigating", "patching", "testing",
        "reviewing", "resolved", "escalated", "wontfix", "rejected"
    ] = "pending"
    report: FailureReport | None = None
    investigation: InvestigationResult | None = None


class AgentState(TypedDict, total=False):
    session_id: str
    repo_path: str
    sandbox_path: str
    bugreport_path: str
    bugs: list[Bug]
    active_bug: Bug | None
    pending_fix: list[CodeChange] | None