from pathlib import Path
from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState, Bug, CodeChange
from src.agents.fix import Fixer
from src.step_logger import save_step_output


def _process_generate_fix_output(output):
    bugs = output.get("bugs", [])
    statuses = [b.status for b in bugs]
    return {"bug_count": len(bugs), "statuses": statuses}


@traceable(run_type="chain", name="generate_fix", project_name="autonomous bugfix", process_outputs=_process_generate_fix_output)
def generate_fix(state: AgentState) -> dict:
    """Calls the Fixer agent to generate patches for the active bug."""
    bug = state.get("active_bug")

    if bug is None:
        for b in state.get("bugs", []):
            if b.status == "patching":
                bug = b
                break

    if bug is None:
        logger.warning("generate_fix: no active or patching bug found")
        return {"bugs": state.get("bugs", []), "active_bug": None}

    if bug.investigation is None:
        logger.warning(f"Bug {bug.bug_id} has no investigation result — skipping fix generation")
        bug.status = "escalated"
        save_step_output(state["session_id"], "generate_fix", {
            "bug_id": bug.bug_id,
            "status": bug.status,
        })
        return {"bugs": state["bugs"], "active_bug": None}

    sandbox_path = state["sandbox_path"]

    try:
        affected_files = bug.investigation.affected_files
        file_contents = {}

        for file_path in affected_files:
            abs_path = Path(file_path)
            if not abs_path.is_absolute():
                abs_path = Path(sandbox_path) / file_path
            try:
                content = abs_path.read_text(encoding="utf-8")
                file_contents[str(abs_path)] = content
            except FileNotFoundError:
                logger.warning(f"Affected file not found in sandbox: {abs_path}")
            except Exception as e:
                logger.warning(f"Failed to read {abs_path}: {e}")

        if not file_contents:
            logger.warning(f"No affected files readable for {bug.bug_id}")
            bug.status = "escalated"
            return {"bugs": state["bugs"], "active_bug": None}

        fixer = Fixer()
        fix_output = fixer.fix(
            report=[bug.investigation],
            sandbox_path=sandbox_path,
        )

        if fix_output is None or not fix_output.changes:
            logger.warning(f"No fix generated for {bug.bug_id}")
            bug.status = "escalated"
            return {"bugs": state["bugs"], "active_bug": None}

        pending_fix = [
            CodeChange(
                file_path=c.file_path,
                old_code=c.old_code,
                new_code=c.new_code,
                description=c.description,
            )
            for c in fix_output.changes
        ]

        bug.status = "patching"
        logger.info(
            f"Bug {bug.bug_id}: generated {len(pending_fix)} change(s)"
        )

    except Exception as e:
        logger.exception(f"Fix generation failed for {bug.bug_id}")
        bug.status = "escalated"
        pending_fix = None

    save_step_output(state["session_id"], "generate_fix", {
        "bug_id": bug.bug_id,
        "status": bug.status,
        "change_count": len(pending_fix) if pending_fix else 0,
    })

    return {"bugs": state["bugs"], "active_bug": bug, "pending_fix": pending_fix}
