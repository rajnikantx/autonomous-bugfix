from typing import TypedDict


class AgentState(TypedDict):
    repo_path: str
    sandbox_path: str
    bugreport_path: str