from typing import TypedDict, Literal, Optional, NotRequired
from dataclasses import dataclass, field
from datetime import datetime


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
    test_output: str = ""
    review_rejected: bool = False
    review_objections: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class AgentState(TypedDict):
    session_id: str
    settings: AgentSettings
    repo_path: str

    sandbox_path: NotRequired[str]
    bug_report_path: NotRequired[str]

    pytest_bugs: NotRequired[list[PytestBug]]
    pending_bugs: NotRequired[list[PytestBug]]
    fixed_bugs: NotRequired[list[PytestBug]]
    escalated_bugs: NotRequired[list[PytestBug]]
    failed_bugs: NotRequired[list[PytestBug]]
    current_bug: NotRequired[Optional[PytestBug]]

    root_cause: NotRequired[str]
    affected_files: NotRequired[list[str]]
    relevant_snippets: NotRequired[dict[str, str]]
    investigation_steps: NotRequired[list[str]]

    fix_attempts: NotRequired[list[FixAttempt]]
    current_fix: NotRequired[Optional[FixAttempt]]

    status: NotRequired[Status]
    retry_count: NotRequired[int]
    error_message: NotRequired[str]
    fix_count: NotRequired[int]
