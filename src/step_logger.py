import json
import sys
from pathlib import Path
from datetime import datetime

from loguru import logger


LOGS_DIR = Path("logs")


def _session_dir(session_id: str) -> Path:
    return LOGS_DIR / session_id


def init_logging(session_id: str) -> Path:
    """Set up loguru file sinks and create logs directory structure."""
    session_path = _session_dir(session_id)
    session_path.mkdir(parents=True, exist_ok=True)

    log_file = session_path / "run.log"
    logger.add(
        str(log_file),
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}",
    )

    logger.info(f"Logging initialized for session {session_id} at {session_path}")
    return session_path


def save_step_output(session_id: str, step_name: str, data: dict) -> Path:
    """Save a step's output as a JSON file in the session's logs directory."""
    session_path = _session_dir(session_id)
    session_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{step_name}.json"
    filepath = session_path / filename

    serializable = _make_serializable(data)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)

    logger.debug(f"Step output saved: {filepath}")
    return filepath


def _make_serializable(obj):
    """Convert dataclass/Pydantic objects to dicts for JSON serialization."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(item) for item in obj]
    return obj
