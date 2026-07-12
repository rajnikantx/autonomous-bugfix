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
            openai_api_key=settings.OPENAI_API_KEY,
            temperature=settings.TEMPERATURE,
            max_retries=settings.MAX_RETRIES,
        ),
        "repo_path": "/home/rajnikant/Github/test-repo"
    }

    config = {
        "configurable": {
            "thread_id": session_id,
        }
    }

    result = graph.invoke(initial_state, config=config)

    report = result.get("report_summary", "")
    if report:
        print("\n" + report)
    else:
        print("\n--- No report generated ---")

    png_data = graph.get_graph().draw_mermaid_png()
    with open("graph.png", "wb") as f:
        f.write(png_data)
    print("Graph saved to graph.png")
