from dotenv import load_dotenv
load_dotenv()

import uuid

from src.graph.workflow import workflow
from src.config import settings
from src.step_logger import init_logging


def main():
    session_id = str(uuid.uuid4())
    init_logging(session_id)

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
