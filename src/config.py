from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {
        "env_file": ".env", 
        "extra": "ignore"
    }
    
    repo_path: str


settings = Settings()