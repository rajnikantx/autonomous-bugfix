import subprocess
import sys
from pathlib import Path

from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.graph.states import AgentState

REPORT_DIR = ".bugfix"
REPORT_FILE = "pytest_report.json"


def scan_bugs(state: AgentState) -> dict:
    """
    Run pytest in the sandbox and store the JSON report.

    1. Execute pytest with --json-report.
    2. Store report in sandbox/.bugfix/pytest_report.json.
    3. Return bug_report_paths for triage to consume.
    """
    sandbox_path = state["sandbox_path"]

    if not Path(sandbox_path).is_dir():
        logger.error(f"Sandbox not found: {sandbox_path}")
        return {"error_message": f"Sandbox not found: {sandbox_path}"}

    report_dir = Path(sandbox_path) / REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / REPORT_FILE

    cmd = [
        "pytest",
        "--json-report",
        f"--json-report-file={REPORT_DIR}/{REPORT_FILE}",
        "--verbose",
        "--tb=short",
        "--no-header",
    ]

    logger.info(f"Scanning bugs in sandbox: {sandbox_path}")

    try:
        result = subprocess.run(
            cmd,
            cwd=sandbox_path,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0 and not report_path.exists():
            logger.warning("pytest failed and no JSON report generated")
            logger.debug(f"stderr: {result.stderr[:500]}")
            return {
                "error_message": f"pytest failed (exit {result.returncode}): {result.stderr[:500]}",
            }

        if not report_path.exists():
            logger.warning("JSON report not found")
            return {"error_message": "pytest ran but no JSON report was generated"}

        logger.success(f"Bug report stored at: {report_path}")
        return {
            "bug_report_path": str(report_path)
        }

    except Exception as e:
        logger.error(f"Failed to scan bugs: {e}")
        return {"error_message": str(e)}


if __name__ == "__main__":
    result = scan_bugs({"sandbox_path": str(Path(__file__).resolve().parents[3])})
    print(f"\nResult: {result}")
