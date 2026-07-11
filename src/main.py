import uuid

from src.config import settings
from src.graph.states import AgentSettings
from src.graph.workflow import graph


if __name__ == "__main__":
    session_id = str(uuid.uuid4())


    initial_state = {
        "session_id": session_id,
        "settings": AgentSettings(
            model_name=settings.MODEL_NAME,
            temperature=settings.TEMPERATURE,
            max_retries=settings.MAX_RETRIES,
        ),
        "repo_path": settings.REPO_PATH,
    }

    config = {
        "configurable": {
            "thread_id": session_id,
        }
    }

    result = graph.invoke(initial_state, config=config)

    print("\n--- Final State ---")
    for key, value in result.items():
        print(f"{key}: {value}")
