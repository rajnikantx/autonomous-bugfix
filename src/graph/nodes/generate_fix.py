from copy import deepcopy
from pathlib import Path
from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState, Bug, CodeChange
from src.agents.fix import Fixer


def _update_bug_in_list(bugs: list[Bug], bug_id: str, updated_bug: Bug) -> list[Bug]:
    new_bugs = deepcopy(bugs)
    for i, b in enumerate(new_bugs):
        if b.bug_id == bug_id:
            new_bugs[i] = updated_bug
            break
    return new_bugs


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
        updated_bug = deepcopy(bug)
        updated_bug.status = "escalated"
        new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
        return {"bugs": new_bugs, "active_bug": None}

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
            updated_bug = deepcopy(bug)
            updated_bug.status = "escalated"
            new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
            return {"bugs": new_bugs, "active_bug": None}

        fixer = Fixer()
        fix_output = fixer.fix(
            report=bug.investigation,
            sandbox_path=sandbox_path,
        )

        if fix_output is None or not fix_output.changes:
            logger.warning(f"No fix generated for {bug.bug_id}")
            updated_bug = deepcopy(bug)
            updated_bug.status = "escalated"
            new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
            return {"bugs": new_bugs, "active_bug": None}

        pending_fix = [
            CodeChange(
                file_path=c.file_path,
                old_code=c.old_code,
                new_code=c.new_code,
                description=c.description,
            )
            for c in fix_output.changes
        ]

        updated_bug = deepcopy(bug)
        updated_bug.status = "patching"
        logger.info(
            f"Bug {bug.bug_id}: generated {len(pending_fix)} change(s)"
        )

    except Exception as e:
        logger.exception(f"Fix generation failed for {bug.bug_id}")
        updated_bug = deepcopy(bug)
        updated_bug.status = "escalated"
        pending_fix = None

    new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
    return {"bugs": new_bugs, "active_bug": updated_bug, "pending_fix": pending_fix}
