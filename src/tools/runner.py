from __future__ import annotations
from dataclasses import dataclass, field
import re


@dataclass
class PytestResult:
    """Structured result of a pytest run."""
    passed: bool = False
    total: int = 0
    num_passed: int = 0
    num_failed: int = 0
    num_errors: int = 0
    failing_tests: list[str] = field(default_factory=list)
    raw_output: str = ""


_LINE_STATUS = re.compile(
    r"^.*?::(?P<test>\w+)\s+(?P<status>PASSED|FAILED|ERROR)\s*$"
)

_SHORT_FAIL = re.compile(
    r"FAILED\s+.*?::(?P<test>\w+)\s+-\s+"
)

_SUMMARY_PASSED = re.compile(r"(\d+)\s+passed")
_SUMMARY_FAILED = re.compile(r"(\d+)\s+failed")
_SUMMARY_ERRORS = re.compile(r"(\d+)\s+error")


def _parse(raw: str) -> PytestResult:
    total = 0
    num_passed = 0
    num_failed = 0
    num_errors = 0
    failing_tests: list[str] = []

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        m = _LINE_STATUS.match(stripped)
        if m:
            status = m.group("status")
            test_name = m.group("test")
            if status == "PASSED":
                num_passed += 1
                total += 1
            elif status == "FAILED":
                num_failed += 1
                total += 1
                failing_tests.append(test_name)
            elif status == "ERROR":
                num_errors += 1
                total += 1
                failing_tests.append(test_name)
            continue

        m = _SHORT_FAIL.match(stripped)
        if m:
            test_name = m.group("test")
            if test_name not in failing_tests:
                failing_tests.append(test_name)

    if total == 0:
        m_p = _SUMMARY_PASSED.search(raw)
        m_f = _SUMMARY_FAILED.search(raw)
        m_e = _SUMMARY_ERRORS.search(raw)
        num_passed = int(m_p.group(1)) if m_p else 0
        num_failed = int(m_f.group(1)) if m_f else 0
        num_errors = int(m_e.group(1)) if m_e else 0
        total = num_passed + num_failed + num_errors

        for m in _SHORT_FAIL.finditer(raw):
            test_name = m.group("test")
            if test_name not in failing_tests:
                failing_tests.append(test_name)

    passed = num_failed == 0 and num_errors == 0

    return PytestResult(
        passed=passed,
        total=total,
        num_passed=num_passed,
        num_failed=num_failed,
        num_errors=num_errors,
        failing_tests=failing_tests,
        raw_output=raw,
    )
