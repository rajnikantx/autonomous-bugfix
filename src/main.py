import argparse
import sys
import uuid

from dotenv import load_dotenv
load_dotenv()

from loguru import logger

from src.graph.workflow import workflow
from src.config import settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="autonomous-bugfix",
        description="Autonomous multi-agent system that discovers, investigates, and fixes Python bugs.",
    )
    parser.add_argument(
        "-r", "--repo",
        type=str,
        default=None,
        help="Path to the target repository (default: REPO_PATH from .env)",
    )
    parser.add_argument(
        "--triage-model",
        type=str,
        default=None,
        help=f"LLM model for the triage agent (default: {settings.TRIAGE_MODEL})",
    )
    parser.add_argument(
        "--investigate-model",
        type=str,
        default=None,
        help=f"LLM model for the investigator agent (default: {settings.INVESTIGATE_MODEL})",
    )
    parser.add_argument(
        "--fix-model",
        type=str,
        default=None,
        help=f"LLM model for the fixer agent (default: {settings.FIX_MODEL})",
    )
    parser.add_argument(
        "--review-model",
        type=str,
        default=None,
        help=f"LLM model for the reviewer agent (default: {settings.REVIEW_MODEL})",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run investigation only, do not apply fixes",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.verbose:
        logger.level("DEBUG")

    if args.repo:
        settings.REPO_PATH = args.repo
    if args.triage_model:
        settings.TRIAGE_MODEL = args.triage_model
    if args.investigate_model:
        settings.INVESTIGATE_MODEL = args.investigate_model
    if args.fix_model:
        settings.FIX_MODEL = args.fix_model
    if args.review_model:
        settings.REVIEW_MODEL = args.review_model

    session_id = str(uuid.uuid4())

    initial_state = {
        "session_id": session_id,
        "repo_path": settings.REPO_PATH,
        "dry_run": args.dry_run,
    }

    config = {
        "configurable": {
            "session_id": session_id
        }
    }

    logger.info(f"Starting autonomous bugfix session {session_id}")
    logger.info(f"Target repo: {settings.REPO_PATH}")
    if args.dry_run:
        logger.info("Dry-run mode: will not apply fixes")

    workflow.invoke(initial_state, config=config)


if __name__ == "__main__":
    main()
