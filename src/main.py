import uuid

from src.graph.workflow import workflow
from src.config import settings

session_id = str(uuid.uuid4())

initial_state = {
    "repo_path": settings.repo_path
}

config = {
    "configurable": {
        "session_id": session_id
    }
}

workflow.invoke(initial_state, config=config)
