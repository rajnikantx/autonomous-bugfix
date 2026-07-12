from __future__ import annotations
from dataclasses import dataclass
import inspect
from typing import Any, Callable


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    callable: Callable
    module: str
    category: str
    signature: str


_registry: dict[str, Tool] = {}


def _register(fn: Callable, *, category: str) -> None:
    name = fn.__name__
    sig = str(inspect.signature(fn))
    desc = (fn.__doc__ or "").strip().split("\n\n")[0].strip()
    _registry[name] = Tool(
        name=name,
        description=desc,
        callable=fn,
        module=fn.__module__,
        category=category,
        signature=f"{name}{sig}",
    )


# ── filesystem tools ───────────────────────────────────────────────────────────
from src.tools.filesystem import (
    read_file,
    list_files,
    apply_fix,
    apply_fix_to_sandbox,
)

_register(read_file, category="filesystem")
_register(list_files, category="filesystem")
_register(apply_fix, category="filesystem")
_register(apply_fix_to_sandbox, category="filesystem")

# ── codebase tools ─────────────────────────────────────────────────────────────
from src.tools.codebase import (
    grep_codebase,
    get_function_definition,
    get_class_definition,
    get_function_callers,
    get_imports,
)

_register(grep_codebase, category="codebase")
_register(get_function_definition, category="codebase")
_register(get_class_definition, category="codebase")
_register(get_function_callers, category="codebase")
_register(get_imports, category="codebase")

# ── sandbox tools ──────────────────────────────────────────────────────────────
from src.tools.sandbox import (
    install_dependencies,
    run_pytest_in_sandbox,
)

_register(install_dependencies, category="sandbox")
_register(run_pytest_in_sandbox, category="sandbox")


# ── Public API ─────────────────────────────────────────────────────────────────

def get_tool(name: str) -> Tool | None:
    """Look up a tool by name. Returns None if not found."""
    return _registry.get(name)


def list_tools(category: str | None = None) -> list[Tool]:
    """Return all registered tools, optionally filtered by category."""
    if category:
        return [t for t in _registry.values() if t.category == category]
    return list(_registry.values())


def get_tool_names(category: str | None = None) -> list[str]:
    """Return names of all registered tools, optionally filtered by category."""
    return [t.name for t in list_tools(category)]


def format_tools_for_prompt(category: str | None = None) -> str:
    """Format all tool signatures and descriptions for use in agent system prompts."""
    parts = []
    for tool in list_tools(category):
        parts.append(f"  {tool.signature}")
        parts.append(f"      {tool.description}")
    return "\n".join(parts)


def get_categories() -> list[str]:
    """Return all distinct tool categories."""
    return sorted({t.category for t in _registry.values()})


AGENT_TOOLS: dict[str, list[str]] = {
    "triage": [],
    "investigator": [
        "read_file",
        "grep_codebase",
        "get_function_definition",
        "get_class_definition",
        "get_function_callers",
        "get_imports",
    ],
    "fixer": [
        "read_file",
    ],
    "tester": [
        "install_dependencies",
        "run_pytest_in_sandbox",
    ],
    "reviewer": [
        "read_file",
    ],
}


def get_agent_tools(agent_name: str) -> list[Tool]:
    """Return the list of registered Tool objects for a given agent.

    Silently skips any tool names not yet in the registry (e.g. sandbox
    tools when runner.py stubs are incomplete).
    Returns an empty list if the agent name is unknown.
    """
    tool_names = AGENT_TOOLS.get(agent_name, [])
    return [t for name in tool_names if (t := _registry.get(name))]
