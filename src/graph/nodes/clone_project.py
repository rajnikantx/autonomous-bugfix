import tempfile
import shutil
from pathlib import Path
from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState


@traceable(run_type="chain", name="clone_project", project_name="autonomous bugfix")
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
        sandbox_path= tempfile.mkdtemp(prefix="bugfix_")
        shutil.copytree(
            repo_path,
            sandbox_path,
            dirs_exist_ok=True
        )
        logger.info(f"sandbox created successfully at {sandbox_path}")

    except Exception as e:
        shutil.rmtree(sandbox_path, ignore_errors=True)
        logger.error(f"sandbox creation failed for {repo_path}")

    return {
        **state,
        "sandbox_path":sandbox_path
    }