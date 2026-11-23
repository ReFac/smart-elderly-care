from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agent_host: str = "0.0.0.0"
    agent_port: int = 8100
    nest_api_base: str = "http://localhost:3000/api"
    nest_token: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    audit_dir: str = str(ROOT / "data" / "audit")
    memory_dir: str = str(ROOT / "data" / "memory")
    policy_path: str = str(ROOT / "policies" / "runtime.yaml")
    wecom_webhook: str = ""
    require_human_review_for_high_risk: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
