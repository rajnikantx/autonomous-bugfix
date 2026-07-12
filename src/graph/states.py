from typing import TypedDict, Literal, Optional, NotRequired
from dataclasses import dataclass, field


Severity = Literal["low", "medium", "high"]
Status = Literal["started", "indexing", "discovering", "triaging", "investigating", "fixing", "testing", "reviewing", "done", "escalated"]


@dataclass
class AgentSettings:
    model_name: str
    openai_api_key: str
    temperature: float
    max_retries: int


@dataclass
class PytestBugTraceback:
    file: str
    line_no: int
    function: str
    code: str


@dataclass
class PytestBug:
    test_name: str
    test_file: str
    source_file: str
    summary: str
    exception_type: str
    severity: Severity
    traceback: list[PytestBugTraceback]
    raw_output: str
    fixable: bool = False
    escalation_reason: str = ""


@dataclass
class FixAttempt:
    file_path: str
    old_code: str
    new_code: str
    explanation: str
    passed: bool = False


@dataclass
class BugProgress:
    bug: PytestBug
    root_cause: str = ""
    affected_files: list[str] = field(default_factory=list)
    relevant_snippets: dict[str, str] = field(default_factory=dict)
    fix_attempts: list[FixAttempt] = field(default_factory=list)
    review_history: list[dict] = field(default_factory=list)
    test_history: list[dict] = field(default_factory=list)
    status: str = "pending"


class AgentState(TypedDict):
    session_id: str
    settings: AgentSettings
    repo_path: str

    sandbox_path: NotRequired[str]
    bug_report_path: NotRequired[str]

    pending_bugs: NotRequired[list[PytestBug]]
    fixed_bugs: NotRequired[list[PytestBug]]
    escalated_bugs: NotRequired[list[PytestBug]]
    failed_bugs: NotRequired[list[PytestBug]]
    current_bug: NotRequired[Optional[PytestBug]]

    root_cause: NotRequired[str]
    affected_files: NotRequired[list[str]]
    relevant_snippets: NotRequired[dict[str, str]]

    current_fix: NotRequired[Optional[FixAttempt]]

    test_decision: NotRequired[str]
    test_output: NotRequired[str]
    review_decision: NotRequired[str]
    review_objections: NotRequired[list[str]]

    report_summary: NotRequired[str]

    status: NotRequired[Status]
    retry_count: NotRequired[int]
    error_message: NotRequired[str]

    bug_progress: NotRequired[dict[str, BugProgress]]
    current_bug_key: NotRequired[str]
