import copy
import json
from dataclasses import asdict

from loguru import logger
from langsmith import traceable

from src.graph.states import AgentState, Bug, InvestigationResult
from src.agents.investigate import Investigate


def _update_bug_in_list(bugs: list[Bug], bug_id: str, updated_bug: Bug) -> list[Bug]:
    """Return a new list with the matching bug replaced by updated_bug."""
    new_bugs = copy.deepcopy(bugs)
    for i, b in enumerate(new_bugs):
        if b.bug_id == bug_id:
            new_bugs[i] = updated_bug
            break
    return new_bugs


def _process_investigate_output(output):
    bugs = output.get("bugs", [])
    statuses = [b.status for b in bugs]
    return {"bug_count": len(bugs), "statuses": statuses}


@traceable(run_type="chain", name="investigate", project_name="autonomous bugfix", process_outputs=_process_investigate_output)
def investigate_node(state: AgentState) -> dict:
    """Investigates the active bug by tracing the codebase."""
    logger.info(f"investigate_node: state keys={list(state.keys())}")

    bug = state.get("active_bug")

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
            updated_bug = copy.deepcopy(bug)
            updated_bug.status = "escalated"
            new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
            return {"bugs": new_bugs, "active_bug": None}

        result = output.results[0]

        updated_bug = copy.deepcopy(bug)
        updated_bug.investigation = InvestigationResult(
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

        investigator_output_path = "logs/investigator_output.json"
        output_data = {
            "bug_id": bug.bug_id,
            "investigation": asdict(updated_bug.investigation) if updated_bug.investigation else None,
        }
        existing = []
        try:
            with open(investigator_output_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            existing = []
        existing.append(output_data)
        with open(investigator_output_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False, default=str)
        logger.debug(f"investigator output appended at {investigator_output_path}")

        step_chain_path = "logs/step_chain.json"
        step_chain = investigator.get_step_chain()
        step_chain_entry = {
            "bug_id": bug.bug_id,
            "steps": [
                {
                    "iteration_number": step.iteration_number,
                    "observation": step.observation,
                    "reasoning": step.reasoning,
                    "action_name": step.action_name,
                    "action_input": step.action_input,
                    "result": step.result,
                    "status": step.status.value,
                    "timestamp": step.timestamp.isoformat(),
                }
                for step in step_chain
            ],
        }
        existing_chains = []
        try:
            with open(step_chain_path, "r", encoding="utf-8") as f:
                existing_chains = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            existing_chains = []
        existing_chains.append(step_chain_entry)
        with open(step_chain_path, "w", encoding="utf-8") as f:
            json.dump(existing_chains, f, indent=2, ensure_ascii=False)
        logger.debug(
            f"Step chain ({len(step_chain)} steps) appended at {step_chain_path}"
        )

        if result.confidence == "high":
            updated_bug.status = "patching"
            logger.info(
                f"Bug {bug.bug_id} -> patching. "
                f"Affected files: {result.affected_files}"
            )
            new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
            return {"bugs": new_bugs, "active_bug": updated_bug}
        else:
            updated_bug.status = "escalated"
            logger.info(
                f"Bug {bug.bug_id} -> escalated (confidence={result.confidence})"
            )
            new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
            return {"bugs": new_bugs, "active_bug": None}

    except Exception as e:
        logger.exception(f"Investigation failed for {bug.bug_id}")
        updated_bug = copy.deepcopy(bug)
        updated_bug.status = "escalated"
        new_bugs = _update_bug_in_list(state["bugs"], bug.bug_id, updated_bug)
        return {"bugs": new_bugs, "active_bug": None}
