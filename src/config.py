from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

DIRECTORY_PATH = Path(__file__).resolve().parent.parent
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    REPO_PATH: str = str(DIRECTORY_PATH)
    MODEL_NAME: str = "gpt-4o"
    OPENAI_API_KEY: str = ""
    TEMPERATURE: float = 0.0
    MAX_RETRIES: int = 3


settings = Settings()
