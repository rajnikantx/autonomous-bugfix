import os
import tempfile
import shutil
from pathlib import Path
from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState


def _process_clone_output(output):
    return {"sandbox_path": str(output.get("sandbox_path", ""))}


@traceable(run_type="chain", name="clone_project", project_name="autonomous bugfix", process_outputs=_process_clone_output)
def clone_project(state: AgentState):
    """
    clone project in sandbox.
    """
    repo_path = state["repo_path"]
    if not Path(repo_path).is_dir():
        logger.error(f"INVALID repository path: {repo_path}")
        raise FileNotFoundError(f"INVALID repo_path: {repo_path}")

    logger.info("creating sandbox")
    try:
        parent = tempfile.mkdtemp(prefix="bugfix_")
        repo_name = Path(repo_path).name
        sandbox_path = os.path.join(parent, repo_name)
        shutil.copytree(repo_path, sandbox_path)
        logger.info(f"sandbox created successfully at {sandbox_path}")

    except Exception as e:
        # clean up parent temp directory on failure
        if "parent" in locals():
            shutil.rmtree(parent, ignore_errors=True)
        logger.exception(f"sandbox creation failed for {repo_path}")
        raise

    return {
        **state,
        "sandbox_path": sandbox_path,
    }