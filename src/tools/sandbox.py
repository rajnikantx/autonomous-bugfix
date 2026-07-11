"""
tools/sandbox.py

Tools: create_sandbox, reset_sandbox, install_dependencies,
       run_pytest_in_sandbox

Rules:
  - All test execution happens here — never on the real repo
  - sandbox_path is a temp copy that can be freely modified and reset
  - Docker is used when available; subprocess fallback otherwise
  - Every function returns a string status or PytestResult
"""

from __future__ import annotations
import os
import shutil
import subprocess
import tempfile

from config import settings
from tools.runner import PytestResult, _parse


# ── Sandbox lifecycle ─────────────────────────────────────────────────────────

def create_sandbox(repo_path: str) -> str:
    """
    Copy the entire repo into a fresh temp directory.

    Returns the sandbox_path (absolute) on success.
    Returns "ERROR: ..." on failure.

    Called once by main.py at startup. The returned path is stored in
    AgentState.sandbox_path and used by all agents for the rest of the run.
    """
    if not os.path.isdir(repo_path):
        return f"ERROR: repo_path does not exist or is not a directory: {repo_path}"

    try:
        # Use a fixed prefix so logs are easy to identify
        sandbox = tempfile.mkdtemp(prefix="bugfix_sandbox_")
        dest    = os.path.join(sandbox, "repo")
        shutil.copytree(repo_path, dest)
        return dest   # return the inner "repo" dir as the sandbox root
    except Exception as e:
        return f"ERROR creating sandbox: {e}"


def reset_sandbox(repo_path: str, sandbox_path: str) -> str:
    """
    Wipe the sandbox and re-copy from the original repo.

    Called by Test Agent before every retry to ensure previous failed
    fix attempts don't accumulate and corrupt the next attempt.

    Returns "OK: ..." on success, "ERROR: ..." on failure.
    """
    if not os.path.isdir(repo_path):
        return f"ERROR: original repo not found: {repo_path}"

    try:
        # Remove the existing sandbox content
        if os.path.exists(sandbox_path):
            shutil.rmtree(sandbox_path)

        # Re-copy from original
        shutil.copytree(repo_path, sandbox_path)
        return f"OK: sandbox reset from {repo_path}"
    except Exception as e:
        return f"ERROR resetting sandbox: {e}"


def install_dependencies(sandbox_path: str, timeout: int = 120) -> str:
    """
    Install Python dependencies inside the sandbox.

    Tries in order:
        1. requirements.txt  (most common)
        2. pyproject.toml    (modern projects)
        3. setup.py          (older projects)

    If none are found, returns a warning but doesn't fail —
    the project may have no external dependencies.

    Returns "OK: ..." on success, "ERROR: ..." on failure.
    """
    # ── requirements.txt ──────────────────────────────────────────────────
    req_file = os.path.join(sandbox_path, "requirements.txt")
    if os.path.exists(req_file):
        result = _run_cmd(
            ["pip", "install", "-r", "requirements.txt", "-q"],
            cwd=sandbox_path,
            timeout=timeout,
        )
        if result.startswith("ERROR"):
            return result
        return f"OK: installed from requirements.txt"

    # ── pyproject.toml ────────────────────────────────────────────────────
    pyproject = os.path.join(sandbox_path, "pyproject.toml")
    if os.path.exists(pyproject):
        result = _run_cmd(
            ["pip", "install", "-e", ".", "-q"],
            cwd=sandbox_path,
            timeout=timeout,
        )
        if result.startswith("ERROR"):
            return result
        return f"OK: installed from pyproject.toml"

    # ── setup.py ─────────────────────────────────────────────────────────
    setup_py = os.path.join(sandbox_path, "setup.py")
    if os.path.exists(setup_py):
        result = _run_cmd(
            ["pip", "install", "-e", ".", "-q"],
            cwd=sandbox_path,
            timeout=timeout,
        )
        if result.startswith("ERROR"):
            return result
        return f"OK: installed from setup.py"

    return "WARNING: no requirements file found — assuming no dependencies needed"


# ── Test execution in sandbox ─────────────────────────────────────────────────

def run_pytest_in_sandbox(sandbox_path: str, timeout: int = 120) -> PytestResult:
    """
    Run the full pytest suite inside the sandbox.

    If DOCKER_ENABLED=True:  runs inside an isolated Docker container
      - memory capped at DOCKER_MEMORY_LIMIT
      - network disabled
      - container destroyed after run

    If DOCKER_ENABLED=False: runs via subprocess in sandbox_path
      - still isolated from real repo (sandbox is a copy)
      - safe for dev machines

    Always returns PytestResult — never raises.
    """
    if settings.DOCKER_ENABLED:
        return _run_in_docker(sandbox_path, timeout)
    return _run_in_subprocess(sandbox_path, timeout)


# ── Docker implementation ─────────────────────────────────────────────────────

def _run_in_docker(sandbox_path: str, timeout: int) -> PytestResult:
    """Run pytest inside an isolated Docker container."""
    try:
        import docker
        client = docker.from_env()

        container = client.containers.run(
            image="python:3.11-slim",
            command=(
                "bash -c '"
                "pip install -r requirements.txt -q 2>/dev/null || true; "
                "python -m pytest -v --tb=short --no-header 2>&1"
                "'"
            ),
            volumes={
                os.path.abspath(sandbox_path): {
                    "bind": "/app",
                    "mode": "rw",
                }
            },
            working_dir="/app",
            detach=True,
            mem_limit=settings.DOCKER_MEMORY_LIMIT,
            network_disabled=True,   # no outbound network from agent-generated code
        )

        try:
            container.wait(timeout=timeout)
        except Exception:
            container.kill()

        raw = container.logs().decode("utf-8", errors="replace")
        container.remove(force=True)

        return _parse(raw)

    except ImportError:
        # docker SDK not installed — fall back to subprocess silently
        return _run_in_subprocess(sandbox_path, timeout)

    except Exception as e:
        return PytestResult(
            passed=False,
            total=0,
            num_passed=0,
            num_failed=0,
            num_errors=0,
            failing_tests=[],
            raw_output=f"ERROR: Docker execution failed: {e}",
        )


# ── Subprocess fallback ───────────────────────────────────────────────────────

def _run_in_subprocess(sandbox_path: str, timeout: int) -> PytestResult:
    """
    Run pytest in sandbox_path via subprocess.
    Safe because sandbox_path is a disposable copy of the real repo.
    """
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", "-v", "--tb=short", "--no-header"],
            cwd=sandbox_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return _parse(proc.stdout + proc.stderr)

    except subprocess.TimeoutExpired:
        return PytestResult(
            passed=False,
            total=0,
            num_passed=0,
            num_failed=0,
            num_errors=0,
            failing_tests=[],
            raw_output=f"ERROR: pytest timed out after {timeout}s",
        )
    except Exception as e:
        return PytestResult(
            passed=False,
            total=0,
            num_passed=0,
            num_failed=0,
            num_errors=0,
            failing_tests=[],
            raw_output=f"ERROR: subprocess failed: {e}",
        )


# ── Shared subprocess helper ──────────────────────────────────────────────────

def _run_cmd(cmd: list[str], cwd: str, timeout: int) -> str:
    """Run a shell command and return 'OK' or 'ERROR: ...'."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return f"ERROR: command failed: {result.stderr.strip()}"
        return "OK"
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"