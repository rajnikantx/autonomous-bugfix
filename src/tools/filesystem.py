"""
tools/filesystem.py

Tools: read_file, list_files, apply_fix, apply_fix_to_sandbox,
       write_bug_report, write_diff_file, write_escalation_file

Rules:
  - Pure file I/O only — no LLM calls, no AgentState, no decisions
  - Every function returns str or list[str] — agents read the return value
  - Errors returned as strings (never raised) — agent decides what to do
"""

from __future__ import annotations
import os
import difflib
from datetime import datetime
from dataclasses import dataclass


# ── Read ──────────────────────────────────────────────────────────────────────

def read_file(file_path: str) -> str:
    """
    Read a file and return content with line numbers.
    Line numbers let the agent reference exact lines in its reasoning.

    Returns error string if file not found — agent handles the error.
    """
    if not os.path.exists(file_path):
        return f"ERROR: file not found: {file_path}"
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        numbered = [f"{i + 1:4d} | {line}" for i, line in enumerate(lines)]
        return "".join(numbered)
    except Exception as e:
        return f"ERROR reading {file_path}: {e}"


def list_files(repo_path: str, extension: str = ".py") -> list[str]:
    """
    Return all files with given extension under repo_path.
    Returns relative paths (relative to repo_path).
    Skips common non-code directories automatically.
    """
    skip = {
        "__pycache__", ".git", "venv", ".venv",
        "node_modules", ".tox", "dist", "build",
        ".mypy_cache", ".pytest_cache", "htmlcov",
    }
    result = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [
            d for d in dirs
            if d not in skip and not d.startswith(".")
        ]
        for fname in files:
            if fname.endswith(extension):
                full = os.path.join(root, fname)
                rel  = os.path.relpath(full, repo_path)
                result.append(rel)
    return sorted(result)


# ── Fix Application ───────────────────────────────────────────────────────────

def apply_fix(file_path: str, old_code: str, new_code: str) -> str:
    """
    Replace old_code with new_code in file_path.

    Requires old_code to appear EXACTLY ONCE — prevents accidental
    multi-replacement which would corrupt the file silently.

    Returns "OK: ..." on success, "ERROR: ..." on failure.
    """
    if not os.path.exists(file_path):
        return f"ERROR: file not found: {file_path}"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"ERROR reading {file_path}: {e}"

    count = content.count(old_code)
    if count == 0:
        return (
            f"ERROR: old_code not found in {file_path}. "
            "Make sure old_code is copied exactly from read_file output "
            "(including indentation and line endings)."
        )
    if count > 1:
        return (
            f"ERROR: old_code appears {count} times in {file_path}. "
            "old_code must be unique — add more surrounding context to make it unique."
        )

    new_content = content.replace(old_code, new_code, 1)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return f"ERROR writing {file_path}: {e}"

    return f"OK: fix applied to {file_path}"


def apply_fix_to_sandbox(
    sandbox_path: str,
    relative_file_path: str,
    old_code: str,
    new_code: str,
) -> str:
    """
    Same as apply_fix but resolves the path inside the sandbox directory.

    Agents always call this — never apply_fix directly on the real repo.
    relative_file_path: e.g. "src/checkout.py" (relative to sandbox root)
    """
    full_path = os.path.join(sandbox_path, relative_file_path)
    return apply_fix(full_path, old_code, new_code)


# ── Output Writers ────────────────────────────────────────────────────────────

def write_bug_report(
    output_dir: str,
    session_id: str,
    fixed_bugs: list,
    failed_bugs: list,
    escalated_bugs: list,
    fix_attempts_map: dict,  # test_name → list[FixAttempt]
) -> str:
    """
    Write .bugfix/report.txt — the human-readable summary of the full run.

    fixed_bugs, failed_bugs, escalated_bugs are lists of PytestBug.
    fix_attempts_map maps test_name → list of FixAttempt for that bug.
    """
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "report.txt")

    total = len(fixed_bugs) + len(failed_bugs) + len(escalated_bugs)
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "=" * 60,
        "  BUG FIX AGENT — SESSION REPORT",
        "=" * 60,
        f"  Session ID : {session_id}",
        f"  Date       : {now}",
        f"  Total bugs : {total}",
        f"  Fixed      : {len(fixed_bugs)}",
        f"  Failed     : {len(failed_bugs)}",
        f"  Escalated  : {len(escalated_bugs)}",
        "=" * 60,
        "",
    ]

    # ── Fixed ──────────────────────────────────────────────────────────────
    if fixed_bugs:
        lines.append("✓  FIXED BUGS")
        lines.append("-" * 60)
        for i, bug in enumerate(fixed_bugs, 1):
            attempts = fix_attempts_map.get(bug.test_name, [])
            winning  = next((a for a in attempts if a.passed), None)
            lines += [
                f"  [{i}] {bug.test_name}",
                f"      Exception : {bug.exception_type}",
                f"      File      : {bug.file_path}:{bug.line_no}",
                f"      Message   : {bug.bug_message}",
                f"      Attempts  : {len(attempts)}",
                f"      Fix       : {winning.explanation if winning else 'N/A'}",
                "",
            ]

    # ── Failed ──────────────────────────────────────────────────────────────
    if failed_bugs:
        lines.append("✗  FAILED BUGS  (agent gave up — needs human)")
        lines.append("-" * 60)
        for i, bug in enumerate(failed_bugs, 1):
            attempts = fix_attempts_map.get(bug.test_name, [])
            lines += [
                f"  [{i}] {bug.test_name}",
                f"      Exception : {bug.exception_type}",
                f"      File      : {bug.file_path}:{bug.line_no}",
                f"      Message   : {bug.bug_message}",
                f"      Attempts  : {len(attempts)} (all failed)",
                "",
            ]

    # ── Escalated ──────────────────────────────────────────────────────────
    if escalated_bugs:
        lines.append("⚠  ESCALATED BUGS  (not attempted — needs human)")
        lines.append("-" * 60)
        for i, bug in enumerate(escalated_bugs, 1):
            lines += [
                f"  [{i}] {bug.test_name}",
                f"      Exception : {bug.exception_type}",
                f"      File      : {bug.file_path}:{bug.line_no}",
                f"      Message   : {bug.bug_message}",
                f"      Reason    : unsupported exception type or ambiguous AssertionError",
                "",
            ]

    lines.append("=" * 60)
    content = "\n".join(lines)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"OK: report written to {path}"
    except Exception as e:
        return f"ERROR writing report: {e}"


def write_diff_file(output_dir: str, session_id: str, fix_attempts: list) -> str:
    """
    Write .bugfix/changes.diff — unified diff of every fix that passed.
    fix_attempts: list of FixAttempt where passed=True.
    """
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "changes.diff")

    all_diffs = []
    for attempt in fix_attempts:
        if not attempt.passed:
            continue
        old_lines = attempt.old_code.splitlines(keepends=True)
        new_lines = attempt.new_code.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{attempt.file_path}",
            tofile=f"b/{attempt.file_path}",
        )
        all_diffs.extend(diff)

    content = "".join(all_diffs) if all_diffs else "# No changes made\n"

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"OK: diff written to {path}"
    except Exception as e:
        return f"ERROR writing diff: {e}"


def write_escalation_file(
    output_dir: str,
    escalated_bugs: list,
    failed_bugs: list,
) -> str:
    """
    Write .bugfix/escalations.txt — actionable list for the human developer.
    escalated_bugs: bugs skipped due to unsupported type or ambiguous assertion.
    failed_bugs: bugs the agent tried and gave up on.
    """
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "escalations.txt")

    lines = [
        "ESCALATIONS — requires human review",
        "=" * 60,
        "",
    ]

    if escalated_bugs:
        lines.append("NOT ATTEMPTED (unsupported exception type):")
        lines.append("-" * 40)
        for bug in escalated_bugs:
            lines += [
                f"  Test    : {bug.test_name}",
                f"  Type    : {bug.exception_type}",
                f"  File    : {bug.file_path}:{bug.line_no}",
                f"  Message : {bug.bug_message}",
                "",
            ]

    if failed_bugs:
        lines.append("ATTEMPTED BUT FAILED (max retries exceeded):")
        lines.append("-" * 40)
        for bug in failed_bugs:
            lines += [
                f"  Test    : {bug.test_name}",
                f"  Type    : {bug.exception_type}",
                f"  File    : {bug.file_path}:{bug.line_no}",
                f"  Message : {bug.bug_message}",
                "",
            ]

    content = "\n".join(lines)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"OK: escalations written to {path}"
    except Exception as e:
        return f"ERROR writing escalations: {e}"