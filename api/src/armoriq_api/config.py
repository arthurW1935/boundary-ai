from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ArmorIQ Guarded MCP Agent"
    app_env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./armoriq.db"
    redis_url: str | None = None
    frontend_origin: str = "http://localhost:3000"
    llm_provider: str = "mock"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"
    max_tool_steps: int = 6
    exa_mcp_enabled: bool = True
    exa_mcp_url: str = "https://mcp.exa.ai/mcp"
    exa_api_key: str | None = None
    remote_mcp_url: str | None = None
    remote_mcp_transport: str = "sse"
    remote_mcp_name: str = "context7"
    approval_ttl_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
