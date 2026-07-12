from src.graph.states import AgentState


def generate_report(state: AgentState) -> dict:
    fixed_bugs = state.get("fixed_bugs", [])
    failed_bugs = state.get("failed_bugs", [])
    escalated_bugs = state.get("escalated_bugs", [])
    pending_bugs = state.get("pending_bugs", [])
    error_message = state.get("error_message", "")
    status = state.get("status", "")
    bug_progress = state.get("bug_progress", {})

    total = len(fixed_bugs) + len(failed_bugs) + len(escalated_bugs) + len(pending_bugs)
    fix_count = len(fixed_bugs)

    lines = []
    lines.append("# Bug Fix Report\n")

    if error_message:
        lines.append(f"**Error:** {error_message}\n")

    if status:
        lines.append(f"**Pipeline status:** {status}\n")

    lines.append(f"**Total bugs found:** {total}")
    lines.append(f"**Fixed:** {fix_count}")
    lines.append(f"**Failed:** {len(failed_bugs)}")
    lines.append(f"**Escalated:** {len(escalated_bugs)}")
    lines.append(f"**Pending (unfixable):** {len(pending_bugs)}")
    lines.append("")

    if error_message:
        lines.append("**Overall status:** Pipeline failed with error.\n")
    elif fix_count == 0 and len(escalated_bugs) == 0:
        lines.append("**Overall status:** No fixes applied.\n")
    elif fix_count == total:
        lines.append("**Overall status:** All bugs fixed.\n")
    else:
        lines.append("**Overall status:** Partial fix.\n")

    for key, prog in bug_progress.items():
        if prog.status == "escalated":
            continue
        lines.append(f"## Bug: {prog.bug.test_name}")
        lines.append(f"- **Status:** {prog.status}")
        lines.append(f"- **File:** {prog.bug.source_file}")
        lines.append(f"- **Severity:** {prog.bug.severity}")
        lines.append(f"- **Summary:** {prog.bug.summary}")
        if prog.root_cause:
            lines.append(f"- **Root cause:** {prog.root_cause[:200]}")
        if prog.affected_files:
            lines.append(f"- **Affected files:** {', '.join(prog.affected_files)}")
        if prog.fix_attempts:
            lines.append(f"- **Fix attempts:** {len(prog.fix_attempts)}")
            for j, attempt in enumerate(prog.fix_attempts, 1):
                status_str = "passed" if attempt.passed else "failed"
                lines.append(f"  - Attempt {j}: {status_str} — {attempt.explanation[:100]}")
        if prog.review_history:
            lines.append(f"- **Reviews:** {len(prog.review_history)}")
            for j, rev in enumerate(prog.review_history, 1):
                lines.append(f"  - Review {j}: {rev['decision']}")
                if rev.get("objections"):
                    for obj in rev["objections"]:
                        lines.append(f"    - {obj}")
        if prog.test_history:
            lines.append(f"- **Tests:** {len(prog.test_history)}")
            for j, test in enumerate(prog.test_history, 1):
                lines.append(f"  - Test {j}: {test['decision']}")
        lines.append("")

    if escalated_bugs:
        lines.append("## Escalated Bugs\n")
        for i, bug in enumerate(escalated_bugs, 1):
            lines.append(f"### {i}. {bug.test_name}")
            lines.append(f"- **File:** {bug.source_file}")
            lines.append(f"- **Severity:** {bug.severity}")
            lines.append(f"- **Summary:** {bug.summary}")
            if bug.escalation_reason:
                lines.append(f"- **Reason:** {bug.escalation_reason}")
            lines.append("")

    if not bug_progress and not escalated_bugs:
        if fixed_bugs:
            lines.append("## Fixed Bugs\n")
            for i, bug in enumerate(fixed_bugs, 1):
                lines.append(f"### {i}. {bug.test_name}")
                lines.append(f"- **File:** {bug.source_file}")
                lines.append(f"- **Severity:** {bug.severity}")
                lines.append(f"- **Summary:** {bug.summary}")
                lines.append("")

        if failed_bugs:
            lines.append("## Failed Bugs\n")
            for i, bug in enumerate(failed_bugs, 1):
                lines.append(f"### {i}. {bug.test_name}")
                lines.append(f"- **File:** {bug.source_file}")
                lines.append(f"- **Severity:** {bug.severity}")
                lines.append(f"- **Summary:** {bug.summary}")
                lines.append("")

    report = "\n".join(lines)
    print(report)

    return {"report_summary": report}
