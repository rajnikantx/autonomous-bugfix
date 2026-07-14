from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState, Bug, InvestigationResult
from src.agents.investigate import Investigate


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
        pydantic_result = investigator.run(
            bug_id=bug.bug_id,
            test_name=bug.report.test_name,
            test_file=bug.report.test_file,
            traceback=bug.report.traceback,
            failure_summary=bug.report.failure_summary,
            exception_type=bug.report.exception_type,
            sandbox_path=state["sandbox_path"],
        )

        bug.investigation = InvestigationResult(
            bug_id=pydantic_result.bug_id,
            test_name=pydantic_result.test_name,
            root_cause=pydantic_result.root_cause,
            affected_files=pydantic_result.affected_files,
            affected_lines=pydantic_result.affected_lines,
            affected_functions=pydantic_result.affected_functions,
            affected_classes=pydantic_result.affected_classes,
            code_snippets=pydantic_result.code_snippets,
            file_reasoning=pydantic_result.file_reasoning,
            confidence=pydantic_result.confidence,
            reasoning_trace=pydantic_result.reasoning_trace,
        )

        logger.info(
            f"Investigation result for {bug.bug_id}: "
            f"confidence={pydantic_result.confidence}, "
            f"affected_files={pydantic_result.affected_files}, "
            f"root_cause={pydantic_result.root_cause}"
        )
        logger.debug(
            f"Reasoning trace ({len(pydantic_result.reasoning_trace)} steps): "
            f"{pydantic_result.reasoning_trace}"
        )

        if pydantic_result.confidence == "high":
            bug.status = "patching"
            logger.info(
                f"Bug {bug.bug_id} -> patching. "
                f"Affected files: {pydantic_result.affected_files}"
            )
        else:
            bug.status = "escalated"
            logger.info(
                f"Bug {bug.bug_id} -> escalated (confidence={pydantic_result.confidence})"
            )

    except Exception as e:
        logger.exception(f"Investigation failed for {bug.bug_id}")
        bug.status = "escalated"

    return {"bugs": state["bugs"], "active_bug": None}
