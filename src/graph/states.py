from typing import TypedDict, Literal, List
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
    test: bool = False
    report: FailureReport | None = None
    investigation: InvestigationResult | None = None
    fix: CodeChange | None = None


class AgentState(TypedDict, total=False):
    session_id: str
    repo_path: str
    sandbox_path: str
    bugreport_path: str
    dry_run: bool
    bugs: list[Bug]
    active_bug: Bug | None
    pending_fix: list[CodeChange] | None
    applied_fixes: list[CodeChange]
    investigation_history: List[InvestigationResult]
    fix_hisory: List[CodeChange]