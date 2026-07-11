"""
tools/codebase.py

Tools: grep_codebase, get_function_definition, get_class_definition,
       get_function_callers, get_imports

Rules:
  - Pure AST + text operations — no LLM, no state, no I/O except reading files
  - All paths returned are relative to repo_path so agents can pass them
    back into read_file / apply_fix_to_sandbox cleanly
"""

from __future__ import annotations
import ast
import os
import re
import fnmatch
from tools.filesystem import list_files


# ── grep ─────────────────────────────────────────────────────────────────────

def grep_codebase(
    repo_path: str,
    pattern: str,
    file_extension: str = ".py",
    max_results: int = 50,
) -> str:
    """
    Search every file in repo_path for pattern (plain text or regex).

    Returns matches as:
        src/checkout.py:47:    user = session['user_id']

    Caps at max_results to avoid flooding agent context.
    """
    try:
        regex = re.compile(pattern)
    except re.error:
        # Not valid regex — treat as plain text
        regex = re.compile(re.escape(pattern))

    results = []
    for rel_path in list_files(repo_path, file_extension):
        full_path = os.path.join(repo_path, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    if regex.search(line):
                        results.append(f"{rel_path}:{lineno}: {line.rstrip()}")
                        if len(results) >= max_results:
                            results.append(
                                f"... truncated at {max_results} results. "
                                "Narrow your pattern to see more."
                            )
                            return "\n".join(results)
        except Exception:
            continue

    return "\n".join(results) if results else f"No matches found for: {pattern!r}"


# ── Function definition ───────────────────────────────────────────────────────

def get_function_definition(repo_path: str, function_name: str) -> str:
    """
    Find the source code of a function by name using AST.

    Searches all Python files. Returns the first match with its full
    source including decorators.

    Returns error string if not found.
    """
    for rel_path in list_files(repo_path, ".py"):
        full_path = os.path.join(repo_path, rel_path)
        result    = _extract_function(full_path, rel_path, function_name)
        if result:
            return result

    return f"ERROR: function '{function_name}' not found in codebase."


def _extract_function(full_path: str, rel_path: str, name: str) -> str | None:
    """
    Internal: parse one file and extract a function definition by name.
    Returns formatted string or None if not found.
    """
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=rel_path)
    except Exception:
        return None

    lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != name:
            continue

        # Include decorator lines
        start = node.decorator_list[0].lineno - 1 if node.decorator_list else node.lineno - 1
        end   = node.end_lineno
        snippet = "\n".join(lines[start:end])

        return (
            f"# Found in: {rel_path}  (lines {start + 1}–{end})\n"
            f"{snippet}"
        )
    return None


# ── Class definition ──────────────────────────────────────────────────────────

def get_class_definition(repo_path: str, class_name: str) -> str:
    """
    Find the full source of a class definition by name using AST.

    Returns the class header + all its methods. Used by Investigator Agent
    when exception_type == 'AttributeError' since the bug is usually on
    a class attribute or method.

    Returns error string if not found.
    """
    for rel_path in list_files(repo_path, ".py"):
        full_path = os.path.join(repo_path, rel_path)
        result    = _extract_class(full_path, rel_path, class_name)
        if result:
            return result

    return f"ERROR: class '{class_name}' not found in codebase."


def _extract_class(full_path: str, rel_path: str, name: str) -> str | None:
    """Internal: parse one file and extract a class definition by name."""
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=rel_path)
    except Exception:
        return None

    lines = source.splitlines()

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name != name:
            continue

        start = node.decorator_list[0].lineno - 1 if node.decorator_list else node.lineno - 1
        end   = node.end_lineno
        snippet = "\n".join(lines[start:end])

        # Summarise methods so the agent can see structure at a glance
        methods = [
            n.name for n in ast.walk(node)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        return (
            f"# Found in: {rel_path}  (lines {start + 1}–{end})\n"
            f"# Methods  : {', '.join(methods)}\n"
            f"{snippet}"
        )
    return None


# ── Function callers ──────────────────────────────────────────────────────────

def get_function_callers(repo_path: str, function_name: str) -> str:
    """
    Find every call site of function_name across the entire codebase using AST.

    Returns formatted list:
        src/checkout.py:47    process_payment(session)
        src/api.py:112        process_payment(req.body)

    Used by Investigator Agent to trace who calls the broken function,
    which often reveals where the bad argument originates.
    """
    results = []

    for rel_path in list_files(repo_path, ".py"):
        full_path = os.path.join(repo_path, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filename=rel_path)
        except Exception:
            continue

        lines = source.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name != function_name:
                continue
            lineno  = node.lineno
            context = lines[lineno - 1].strip() if lineno <= len(lines) else ""
            results.append(f"{rel_path}:{lineno:4d}    {context}")

    if not results:
        return f"No callers found for '{function_name}'"
    return "\n".join(results)


def _call_name(node: ast.Call) -> str:
    """Extract bare function name from a Call node."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


# ── Imports ───────────────────────────────────────────────────────────────────

def get_imports(repo_path: str, relative_file_path: str) -> str:
    """
    Return all import statements from a single file using AST.

    Tells the Investigator Agent where symbols come from — critical for
    tracing a function or variable back to its origin file.

    Example output:
        import os
        from pathlib import Path
        from src.inventory import get_inventory   ← origin of the buggy function

    Returns error string if file not found or unparseable.
    """
    full_path = os.path.join(repo_path, relative_file_path)

    if not os.path.exists(full_path):
        return f"ERROR: file not found: {relative_file_path}"

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=relative_file_path)
    except SyntaxError as e:
        return f"ERROR: cannot parse {relative_file_path}: {e}"
    except Exception as e:
        return f"ERROR reading {relative_file_path}: {e}"

    lines  = source.splitlines()
    result = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # import os, import sys
            for alias in node.names:
                asname = f" as {alias.asname}" if alias.asname else ""
                result.append(
                    (node.lineno, f"import {alias.name}{asname}")
                )
        elif isinstance(node, ast.ImportFrom):
            # from x import y
            module  = node.module or ""
            dots    = "." * (node.level or 0)
            names   = ", ".join(
                (f"{a.name} as {a.asname}" if a.asname else a.name)
                for a in node.names
            )
            result.append(
                (node.lineno, f"from {dots}{module} import {names}")
            )

    if not result:
        return f"No imports found in {relative_file_path}"

    # Sort by line number, format with line numbers
    result.sort(key=lambda x: x[0])
    formatted = [f"{lineno:4d} | {stmt}" for lineno, stmt in result]
    return f"# Imports in {relative_file_path}\n" + "\n".join(formatted)