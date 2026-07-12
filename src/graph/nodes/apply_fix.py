import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState
from src.tools.filesystem import apply_fix_to_sandbox


def apply_fix(state: AgentState) -> dict:
    """
    Apply the proposed fix to the sandbox.

    Uses apply_fix_to_sandbox to replace old_code with new_code.
    """
    current_fix = state.get("current_fix")
    if not current_fix:
        logger.error("No current_fix set — cannot apply fix")
        return {"error_message": "No current_fix set"}

    sandbox = state.get("sandbox_path")
    if not sandbox or not Path(sandbox).is_dir():
        logger.error(f"Sandbox not found: {sandbox}")
        return {"error_message": f"Sandbox not found: {sandbox}"}

    if not current_fix.old_code or not current_fix.new_code:
        logger.error("current_fix has empty old_code/new_code")
        return {"error_message": "Fix has empty old_code/new_code"}

    logger.info(f"Applying fix to {current_fix.file_path}")
    logger.debug(f"old_code: {current_fix.old_code[:100]}...")
    logger.debug(f"new_code: {current_fix.new_code[:100]}...")

    result = apply_fix_to_sandbox(
        sandbox_path=sandbox,
        relative_file_path=current_fix.file_path,
        old_code=current_fix.old_code,
        new_code=current_fix.new_code,
    )

    if result.startswith("ERROR"):
        logger.error(f"Fix application failed: {result}")
        current_fix.passed = False
        return {
            "current_fix": current_fix,
            "error_message": result,
        }

    logger.success(f"Fix applied: {result}")
    current_fix.passed = True

    return {"current_fix": current_fix}
