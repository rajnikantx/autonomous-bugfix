from pathlib import Path
import shutil
import tempfile
import subprocess
from loguru import logger

def create_sandbox(repo_path: str) -> str:
    """creating sandbox for cloning the target directory"""
    sandbox_path= tempfile.mkdtemp(prefix= "bugfix_")
    logger.info(f"settingup sandbox in : {sandbox_path}")
    try:
        shutil.copytree(
            repo_path,
            sandbox_path,
            ignore= shutil.ignore_patterns(
                ".git", "__pycache__", ".venv", "*.pyc", ".pytest_cache", ".bugfix",
            ),
            dirs_exist_ok= True
        )
        logger.success(f"sandbox created successfully at : {sandbox_path}")
        return sandbox_path

    except Exception as e:
        logger.error(f"Failed to create sandbox: {e}")
        raise


def install_dependencies(sandbox_path: str):
    """install dependencies required for running the cloned project in the sandbox."""
    checks= [
        ("requirements.txt", ["pip","install","-r","requirements.txt","-q"]),
        ("pyproject.toml", ["pip","install","-e",".","-q"]),
        ("setup.py", ["pip","install","-e",".","-q"])
    ]

    for filename,cmd in checks:
        if (Path(sandbox_path) / filename).exists():
            logger.info(f"Installing dependencies from {filename}")
            try:
                result= subprocess.run(
                    cmd,
                    cwd= sandbox_path,
                    capture_output= True,
                    text= True,
                    timeout= 120
                )
                if result.returncode != 0:
                    logger.error(f"Failed to install from {filename}: {result.stderr.strip()}")
                    return False
                logger.success(f"Dependencies installed from {filename}")
                return True

            except subprocess.TimeoutExpired:
                logger.error(f"pip timed out installing from {filename}")
                return False
            except Exception as e:
                logger.error(f"Error installing dependencies: {e}")
                return False

    logger.warning("No dependency file found (requirements.txt, pyproject.toml, setup.py)")
    return False


def reset_sandbox(sandbox_path: str, repo_path: str):
    """wipe sandbox and re-copy from the original repo"""
    if not Path(repo_path).is_dir():
        logger.error(f"Original repo not found: {repo_path}")
        return False

    try:
        if Path(sandbox_path).exists():
            shutil.rmtree(sandbox_path)
        shutil.copytree(repo_path, sandbox_path)
        logger.success("Sandbox reset")
        return True

    except Exception as e:
        logger.error(f"Failed to reset sandbox: {e}")
        return False


def destroy_sandbox(sandbox_path: str):
    """Destroying sandbox"""
    if not Path(sandbox_path).is_dir():
        logger.warning(f"Sandbox not found: {sandbox_path}")
        return False

    try:
        shutil.rmtree(sandbox_path)
        logger.success(f"Sandbox destroyed: {sandbox_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to destroy sandbox: {e}")
        return False
