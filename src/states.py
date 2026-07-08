from typing import TypedDict

class PytestBug:
    """All details of pytest bugs"""
    line_no: int

class AgentState(TypedDict):
    bug_type: str 
    bug_details: Bug
