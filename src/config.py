from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {
        "env_file": ".env", 
        "extra": "ignore"
    }
    OPENAI_API_KEY: str
    REPO_PATH: str
    TRIAGE_MODEL: str = "gpt-4o"
    INVESTIGATE_MODEL: str = "gpt-4o"
    FIX_MODEL: str = "gpt-4o"
    REVIEW_MODEL: str = "gpt-4o"

settings = Settings()