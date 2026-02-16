from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8776
    log_dir: str = "logs"
    default_restart_timeout: int = 10

    model_config = SettingsConfigDict(env_prefix="LLM_SHELL_", env_file=".env")


settings = Settings()
