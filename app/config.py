from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openai_api_key: Optional[str] = None
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    max_concurrent_runs: int = 3
    default_budget_cap: float = 10.0
    max_budget_cap: float = 100.0
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]

    # Model configuration
    box1_model: str = "o4-mini"
    box2_model: str = "gpt-4.1"
    specialist_model: str = "gpt-4.1-mini"
    gate_model: str = "gpt-4.1-nano"

    # Box1 reasoning token cap per cycle
    box1_max_completion_tokens: int = 16384

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


settings = Settings()
