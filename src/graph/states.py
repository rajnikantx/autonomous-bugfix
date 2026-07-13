from typing import TypedDict, Optional


class AgentState(TypedDict):
    repo_path: str
    sandbox_path: Optional[str] = None
