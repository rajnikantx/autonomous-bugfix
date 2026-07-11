from typing import TypedDict, Literal, Optional, NotRequired
from dataclasses import dataclass, field
from datetime import datetime


Severity = Literal["low", "medium", "high"]
FailureType = Literal["IndexError", "AttributeError", "TypeError", "AssertionError", "KeyError", "ValueError", "ImportError", "ModuleNotFoundError", "NameError"]
FailureMode = Literal["FAILED", "ERROR"]
Status = Literal["started", "indexing", "discovering", "triaging", "investigating", "fixing", "testing", "reviewing", "done", "escalated"]


@dataclass
class AgentSettings:
    """Runtime configuration that agents read"""
    model_name: str 
    temperature: float
    max_retries: int

@dataclass
class PytestBugTraceback:
    """Traceback of a pytest bugs"""
    path: str
    line_no: int
    message: str

@dataclass
class PytestBug:
    """All details of pytest bugs"""
    test_name: str
    line_no: int
    file_path: str
    bug_message: str
    exception_type: str
    failure_type: FailureType #IndexError, AttributeError, TypeError, AssertionError
    failure_mode: FailureMode
    severity: Severity
    traceback: list[PytestBugTraceback]
    longrepr: str
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

@dataclass
class Corrected:
    """Bugs after correction"""
    file_path: str
    corrected_code: str

class AgentState(TypedDict):
    session_id: str
    settings: AgentSettings
    repo_path: str

    sandbox_path: NotRequired[str]
    bug_report_path: NotRequired[str]

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