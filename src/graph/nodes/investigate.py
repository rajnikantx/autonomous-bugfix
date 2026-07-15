from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState, Bug, InvestigationResult
from src.agents.investigate import Investigate
from src.step_logger import save_step_output


def _get_active_bug(state: AgentState) -> Bug | None:
    return state.get("active_bug")


def _process_investigate_output(output):
    bugs = output.get("bugs", [])
    statuses = [b.status for b in bugs]
    return {"bug_count": len(bugs), "statuses": statuses}


@traceable(run_type="chain", name="investigate", project_name="autonomous bugfix", process_outputs=_process_investigate_output)
def investigate_node(state: AgentState) -> dict:
    """Investigates the active bug by tracing the codebase."""
    logger.info(f"investigate_node: state keys={list(state.keys())}")

    bug = _get_active_bug(state)

    if bug is None:
        raise ValueError("No active bug to investigate")

    if bug.report is None:
        raise ValueError(f"Bug {bug.bug_id} has no failure report")

    logger.info(
        f"Active bug: id={bug.bug_id}, status={bug.status}, "
        f"test={bug.report.test_name}, file={bug.report.test_file}, "
        f"severity={bug.report.severity}"
    )

    logger.info(f"Investigating bug {bug.bug_id}: {bug.report.test_name}")

    try:
        investigator = Investigate()
        output = investigator.investigate(
            bug_id=bug.bug_id,
            test_name=bug.report.test_name,
            test_file=bug.report.test_file,
            traceback=bug.report.traceback,
            failure_summary=bug.report.failure_summary,
            exception_type=bug.report.exception_type,
            sandbox_path=state["sandbox_path"],
        )

        if not output.results:
            logger.warning(f"No investigation results for {bug.bug_id}")
            bug.status = "escalated"
            save_step_output(state["session_id"], "investigate", {
                "bug_id": bug.bug_id,
                "status": bug.status,
                "investigation": None,
            })
            return {"bugs": state["bugs"], "active_bug": None}

        result = output.results[0]

        bug.investigation = InvestigationResult(
            bug_id=result.bug_id,
            test_name=result.test_name,
            root_cause=result.root_cause,
            affected_files=result.affected_files,
            affected_lines=result.affected_lines,
            affected_functions=result.affected_functions,
            affected_classes=result.affected_classes,
            code_snippets=result.code_snippets,
            file_reasoning=result.file_reasoning,
            confidence=result.confidence,
            reasoning_trace=result.reasoning_trace,
        )

        logger.info(
            f"Investigation result for {bug.bug_id}: "
            f"confidence={result.confidence}, "
            f"affected_files={result.affected_files}, "
            f"root_cause={result.root_cause}"
        )
        logger.debug(
            f"Reasoning trace ({len(result.reasoning_trace)} steps): "
            f"{result.reasoning_trace}"
        )

        if result.confidence == "high":
            bug.status = "patching"
            logger.info(
                f"Bug {bug.bug_id} -> patching. "
                f"Affected files: {result.affected_files}"
            )
            save_step_output(state["session_id"], "investigate", {
                "bug_id": bug.bug_id,
                "status": bug.status,
                "investigation": bug.investigation,
            })
            return {"bugs": state["bugs"], "active_bug": bug}
        else:
            bug.status = "escalated"
            logger.info(
                f"Bug {bug.bug_id} -> escalated (confidence={result.confidence})"
            )
            save_step_output(state["session_id"], "investigate", {
                "bug_id": bug.bug_id,
                "status": bug.status,
                "investigation": bug.investigation,
            })
            return {"bugs": state["bugs"], "active_bug": None}

    except Exception as e:
        logger.exception(f"Investigation failed for {bug.bug_id}")
        bug.status = "escalated"
        save_step_output(state["session_id"], "investigate", {
            "bug_id": bug.bug_id,
            "status": bug.status,
            "investigation": None,
        })
        return {"bugs": state["bugs"], "active_bug": None}
