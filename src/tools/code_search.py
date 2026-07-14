from __future__ import annotations
import ast
import os
import re
from typing import Optional


# ── Internal: file walker ─────────────────────────────────────────────────────

def _walk_python_files(root: str) -> list[str]:
    """
    Return absolute paths of all .py files under root.
    Skips common non-code directories.
    """
    skip = {
        "__pycache__", ".git", "venv", ".venv",
        "node_modules", ".tox", "dist", "build",
        ".mypy_cache", ".pytest_cache", "htmlcov",
    }
    result = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for fname in files:
            if fname.endswith(".py"):
                result.append(os.path.join(dirpath, fname))
    return sorted(result)


def _relative(path: str, root: str) -> str:
    """Return path relative to root for cleaner output."""
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def _read_source(file_path: str) -> tuple[str, list[str]]:
    """Read source and return (source_str, lines_list)."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()
    return source, source.splitlines()


# ── 1. extract_snippet ────────────────────────────────────────────────────────

def extract_snippet(
    file_path: str,
    line_no: int,
    radius: int = 10,
) -> str:
    """
    Return lines around line_no with line numbers.

    radius=10 means 10 lines before and 10 lines after — 21 lines total.
    The crash line is marked with >>>  for easy identification.

    This is the DEFAULT first tool for the Investigator Agent.
    Always call this before read_file — far less context usage.

    file_path: absolute path inside sandbox
    line_no:   1-based line number (from stack trace)
    radius:    lines before and after to include
    """
    if not os.path.exists(file_path):
        return f"ERROR: file not found: {file_path}"

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"ERROR reading {file_path}: {e}"

    total    = len(lines)
    line_idx = line_no - 1  # convert to 0-based

    if line_idx < 0 or line_idx >= total:
        return (
            f"ERROR: line_no {line_no} out of range "
            f"(file has {total} lines): {file_path}"
        )

    start = max(0, line_idx - radius)
    end   = min(total, line_idx + radius + 1)

    result_lines = []
    for i in range(start, end):
        lineno  = i + 1
        content = lines[i].rstrip("\n")
        marker  = ">>>" if i == line_idx else "   "
        result_lines.append(f"{lineno:4d} {marker} {content}")

    header = f"# {file_path}  (lines {start + 1}–{end}, crash at line {line_no})\n"
    return header + "\n".join(result_lines)


# ── 2. grep_codebase ──────────────────────────────────────────────────────────

def grep_codebase(
    pattern: str,
    sandbox_path: str,
    file_extension: str = ".py",
    max_results: int = 50,
) -> str:
    """
    Search all files under sandbox_path for pattern (text or regex).

    Returns matches as:
        src/checkout.py:47:    user = session['user_id']

    Replaces get_function_callers for simple lookups:
        grep_codebase("def process_payment")   → find definition
        grep_codebase("process_payment(")      → find all callers
        grep_codebase("class PaymentService")  → find class

    Use get_function_callers for precise AST-based caller lookup
    when grep gives too many false positives.

    Caps at max_results to protect context window.
    """
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(pattern), re.IGNORECASE)

    results  = []
    searched = 0

    for abs_path in _walk_python_files(sandbox_path):
        if not abs_path.endswith(file_extension):
            continue
        rel_path = _relative(abs_path, sandbox_path)
        searched += 1

        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    if regex.search(line):
                        results.append(
                            f"{rel_path}:{lineno}: {line.rstrip()}"
                        )
                        if len(results) >= max_results:
                            results.append(
                                f"\n... truncated at {max_results} results "
                                f"({searched} files searched). "
                                "Narrow your pattern to see more."
                            )
                            return "\n".join(results)
        except Exception:
            continue

    if not results:
        return (
            f"No matches for {pattern!r} "
            f"({searched} files searched in {sandbox_path})"
        )

    return f"# {len(results)} match(es) for {pattern!r}\n" + "\n".join(results)


# ── 3. get_function_definition ────────────────────────────────────────────────

def get_function_definition(
    function_name: str,
    sandbox_path: str,
) -> str:
    """
    Find and return the COMPLETE source of a function using AST.

    Searches all Python files in sandbox_path.
    Returns the FULL function body regardless of length —
    unlike extract_snippet which cuts off at a fixed radius.

    Includes decorators. Handles async functions.
    Returns the first match found.

    Use when:
      - Function body is longer than extract_snippet's radius
      - You need the complete function, not just lines around the crash
    """
    for abs_path in _walk_python_files(sandbox_path):
        rel_path = _relative(abs_path, sandbox_path)
        result   = _extract_function_from_file(abs_path, rel_path, function_name)
        if result:
            return result

    return (
        f"ERROR: function '{function_name}' not found in {sandbox_path}.\n"
        f"Try grep_codebase('def {function_name}') to verify it exists."
    )


def _extract_function_from_file(
    abs_path: str,
    rel_path: str,
    name: str,
) -> Optional[str]:
    """Internal: extract one function from one file."""
    try:
        source, lines = _read_source(abs_path)
        tree          = ast.parse(source, filename=rel_path)
    except Exception:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != name:
            continue

        # Include decorator lines above the def
        start = (
            node.decorator_list[0].lineno - 1
            if node.decorator_list
            else node.lineno - 1
        )
        end     = node.end_lineno
        snippet = "\n".join(lines[start:end])

        async_prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        return (
            f"# {rel_path}  lines {start + 1}–{end}\n"
            f"# {async_prefix}def {name}\n"
            + "\n".join(f"{start + i + 1:4d} | {l}" for i, l in enumerate(lines[start:end]))
        )

    return None


# ── 4. get_class_definition ───────────────────────────────────────────────────

def get_class_definition(
    class_name: str,
    sandbox_path: str,
) -> str:
    """
    Find and return the COMPLETE source of a class using AST.

    Searches all Python files in sandbox_path.
    Returns full class body including ALL methods regardless of class size.

    Also returns a method summary at the top so agent can see
    the full structure before reading 200 lines.

    Use when:
      - Bug is AttributeError — need to understand full class structure
      - Need to see __init__, properties, and all methods together
      - Class is too large for extract_snippet
    """
    for abs_path in _walk_python_files(sandbox_path):
        rel_path = _relative(abs_path, sandbox_path)
        result   = _extract_class_from_file(abs_path, rel_path, class_name)
        if result:
            return result

    return (
        f"ERROR: class '{class_name}' not found in {sandbox_path}.\n"
        f"Try grep_codebase('class {class_name}') to verify it exists."
    )


def _extract_class_from_file(
    abs_path: str,
    rel_path: str,
    name: str,
) -> Optional[str]:
    """Internal: extract one class from one file."""
    try:
        source, lines = _read_source(abs_path)
        tree          = ast.parse(source, filename=rel_path)
    except Exception:
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name != name:
            continue

        start = (
            node.decorator_list[0].lineno - 1
            if node.decorator_list
            else node.lineno - 1
        )
        end = node.end_lineno

        # Build method summary
        methods = []
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                prefix = "async " if isinstance(child, ast.AsyncFunctionDef) else ""
                args   = [a.arg for a in child.args.args]
                methods.append(
                    f"  line {child.lineno:3d}: {prefix}def {child.name}({', '.join(args)})"
                )

        method_summary = "\n".join(methods) if methods else "  (no methods)"
        numbered       = "\n".join(
            f"{start + i + 1:4d} | {l}"
            for i, l in enumerate(lines[start:end])
        )

        return (
            f"# {rel_path}  lines {start + 1}–{end}\n"
            f"# class {name} — methods:\n"
            f"{method_summary}\n"
            f"# Full source:\n"
            f"{numbered}"
        )

    return None


# ── 5. get_function_callers ───────────────────────────────────────────────────

def get_function_callers(
    function_name: str,
    sandbox_path: str,
) -> str:
    """
    Find ALL call sites of function_name across the codebase using AST.

    Returns file:line: context for each call site.
    Handles both:
      - Direct calls:  process_payment(session)
      - Method calls:  self.process_payment(session)
                       obj.process_payment(session)

    More precise than grep_codebase("function_name(") because:
      - No false positives from comments
      - No false positives from similar names (e.g. process_payments)
      - Correctly identifies method calls vs attribute access

    Use when:
      - grep_codebase gives too many false positives
      - Need to understand all entry points to a broken function
    """
    results   = []
    searched  = 0

    for abs_path in _walk_python_files(sandbox_path):
        rel_path = _relative(abs_path, sandbox_path)
        searched += 1

        try:
            source, lines = _read_source(abs_path)
            tree          = ast.parse(source, filename=rel_path)
        except Exception:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # Match direct call: function_name(...)
            is_direct = (
                isinstance(node.func, ast.Name)
                and node.func.id == function_name
            )
            # Match method call: obj.function_name(...)
            is_method = (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == function_name
            )

            if not (is_direct or is_method):
                continue

            lineno  = node.lineno
            context = lines[lineno - 1].strip() if lineno <= len(lines) else ""

            # Find which function/method this call is inside
            parent_func = _find_parent_function(tree, node)
            location    = f" (inside {parent_func})" if parent_func else ""

            results.append(
                f"{rel_path}:{lineno}{location}: {context}"
            )

    if not results:
        return (
            f"No callers found for '{function_name}' "
            f"({searched} files searched).\n"
            f"Try grep_codebase('{function_name}(') as fallback."
        )

    header = f"# {len(results)} caller(s) of '{function_name}'\n"
    return header + "\n".join(results)


def _find_parent_function(tree: ast.AST, target: ast.Call) -> Optional[str]:
    """
    Internal: find the name of the function that contains a Call node.
    Used to give caller context like "inside process_payment".
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Check if target is anywhere inside this function
        for child in ast.walk(node):
            if child is target:
                return node.name
    return None


# ── 6. get_functions_of_file ──────────────────────────────────────────────────

def get_functions_of_file(file_path: str) -> str:
    """
    Return all functions and methods defined in a file.

    Output format:
        line  12: def process_payment(session, amount)
        line  34: def _validate_session(session)
        line  67: class PaymentService
          line  70:   def __init__(self)
          line  85:   def charge(self, user, amount)
          line  102:  async def refund(self, transaction_id)

    Use when:
      - Agent needs file structure overview before deciding what to read
      - Agent wants to find which method handles a specific concern
      - Faster than read_file for understanding a file's contents

    file_path: absolute path to the file
    """
    if not os.path.exists(file_path):
        return f"ERROR: file not found: {file_path}"

    try:
        source, _ = _read_source(file_path)
        tree      = ast.parse(source, filename=file_path)
    except SyntaxError as e:
        return f"ERROR: cannot parse {file_path}: SyntaxError at line {e.lineno}: {e.msg}"
    except Exception as e:
        return f"ERROR parsing {file_path}: {e}"

    lines_out = [f"# Functions and classes in {file_path}\n"]

    for node in ast.iter_child_nodes(tree):
        # Top-level functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            args   = _format_args(node)
            lines_out.append(f"line {node.lineno:4d}: {prefix}def {node.name}({args})")

        # Top-level classes + their methods
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(_get_name(b) for b in node.bases)
            base_str = f"({bases})" if bases else ""
            lines_out.append(f"line {node.lineno:4d}: class {node.name}{base_str}")

            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = "async " if isinstance(child, ast.AsyncFunctionDef) else ""
                    args   = _format_args(child)
                    lines_out.append(
                        f"  line {child.lineno:4d}:   {prefix}def {child.name}({args})"
                    )

    if len(lines_out) == 1:
        return f"No functions or classes found in {file_path}"

    return "\n".join(lines_out)


def _format_args(node: ast.FunctionDef) -> str:
    """Format function arguments as a readable string."""
    args = []
    all_args = node.args

    # Regular args
    for a in all_args.args:
        args.append(a.arg)

    # *args
    if all_args.vararg:
        args.append(f"*{all_args.vararg.arg}")

    # **kwargs
    if all_args.kwarg:
        args.append(f"**{all_args.kwarg.arg}")

    return ", ".join(args)


def _get_name(node: ast.expr) -> str:
    """Get a readable name from an AST expression node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_get_name(node.value)}.{node.attr}"
    return "?"


# ── 7. get_imports_of_file ────────────────────────────────────────────────────

def get_imports_of_file(file_path: str) -> str:
    """
    Return all import statements from a file with line numbers.

    Output format:
        line   1: import os
        line   2: import sys
        line   4: from pathlib import Path
        line   5: from src.inventory import get_inventory, InventoryItem
        line   6: from . import utils   (relative import)

    Use when:
      - Bug involves a NameError or AttributeError on an imported symbol
      - Agent needs to trace where a function/class comes from
      - Agent suspects a missing or wrong import is the root cause

    file_path: absolute path to the file
    """
    if not os.path.exists(file_path):
        return f"ERROR: file not found: {file_path}"

    try:
        source, _ = _read_source(file_path)
        tree      = ast.parse(source, filename=file_path)
    except SyntaxError as e:
        return f"ERROR: cannot parse {file_path}: SyntaxError at line {e.lineno}: {e.msg}"
    except Exception as e:
        return f"ERROR parsing {file_path}: {e}"

    imports = []

    for node in ast.walk(tree):
        # import os  /  import os, sys  /  import os as operating_system
        if isinstance(node, ast.Import):
            for alias in node.names:
                as_str = f" as {alias.asname}" if alias.asname else ""
                imports.append((node.lineno, f"import {alias.name}{as_str}"))

        # from x import y  /  from . import y  /  from ..x import y
        elif isinstance(node, ast.ImportFrom):
            module  = node.module or ""
            dots    = "." * (node.level or 0)  # relative import dots
            names   = ", ".join(
                (f"{a.name} as {a.asname}" if a.asname else a.name)
                for a in node.names
            )
            relative_note = "  (relative import)" if node.level else ""
            imports.append((
                node.lineno,
                f"from {dots}{module} import {names}{relative_note}"
            ))

    if not imports:
        return f"No imports found in {file_path}"

    imports.sort(key=lambda x: x[0])
    lines_out = [f"# Imports in {file_path}  ({len(imports)} total)\n"]
    for lineno, stmt in imports:
        lines_out.append(f"line {lineno:4d}: {stmt}")

    return "\n".join(lines_out)