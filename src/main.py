import sys
import uuid

from dotenv import load_dotenv
load_dotenv()

from loguru import logger

# logger.remove()
# logger.add("logs/run.log", level="DEBUG", format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}")

from src.graph.workflow import workflow
from src.config import settings


def main():
    session_id = str(uuid.uuid4())

    initial_state = {
        "session_id": session_id,
        "repo_path": settings.REPO_PATH,
    }

    config = {
        "configurable": {
            "session_id": session_id
        }
    }

    workflow.invoke(initial_state, config=config)


if __name__ == "__main__":
    main()
