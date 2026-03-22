from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openai_api_key: Optional[str] = None
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    max_concurrent_runs: int = 3
    default_budget_cap: float = 10.0
    max_budget_cap: float = 100.0

    # Model configuration
    box1_model: str = "o4-mini"
    box2_model: str = "gpt-4.1"
    specialist_model: str = "gpt-4.1-mini"
    gate_model: str = "gpt-4.1-nano"

    # Box1 reasoning token cap per cycle
    box1_max_completion_tokens: int = 16384


settings = Settings()
