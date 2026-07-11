import shutil
import tempfile
import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState


def clone_project(state: AgentState) -> dict:
    """
    Validate repo_path and create a sandbox copy for safe modification.

    1. Confirm repo_path exists and is a directory.
    2. Copy the repo into a temp sandbox, ignoring heavy/irrelevant dirs.
    3. Return updated state with sandbox_path set.
    """
    repo_path = state["repo_path"]

    if not Path(repo_path).is_dir():
        raise ValueError(f"repo_path is not a valid directory: {repo_path}")

    logger.info(f"Creating sandbox for repo: {repo_path}")

    try:
        sandbox = tempfile.mkdtemp(prefix="bugfix_sandbox_")

        shutil.copytree(
            repo_path,
            sandbox,
            ignore=shutil.ignore_patterns(
                ".git", "__pycache__", ".venv", "*.pyc",
                ".pytest_cache", ".bugfix", "node_modules",
            ),
            dirs_exist_ok=True,
        )

        logger.success(f"Sandbox created at: {sandbox}")

        state["sandbox_path"] = sandbox
        for key, value in state.items():
            logger.info(f"  {key}: {value}")

        return {"sandbox_path": sandbox}

    except Exception as e:
        logger.error(f"Failed to create sandbox: {e}")
        raise


if __name__ == "__main__":
    result = clone_project({"repo_path": str(Path(__file__).resolve().parents[3])})
    print(f"\nResult: {result}")
