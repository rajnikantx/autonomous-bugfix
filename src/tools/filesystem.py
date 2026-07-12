"""
tools/filesystem.py

Tools: read_file, list_files, apply_fix, apply_fix_to_sandbox

Rules:
  - Pure file I/O only — no LLM calls, no AgentState, no decisions
  - Every function returns str or list[str] — agents read the return value
  - Errors returned as strings (never raised) — agent decides what to do
"""

from __future__ import annotations
import os


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

