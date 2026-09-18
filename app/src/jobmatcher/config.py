"""Application settings, wired from environment variables (see root .env.example)."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM gateway -------------------------------------------------------
    gateway_provider: str = "zen"
    gateway_model: str = "gpt-5.4-mini"
    gateway_base_url: str | None = None
    llm_timeout: float = 60.0
    llm_max_retries: int = 3
    llm_max_concurrency: int = 4
    llm_cost_limit_usd: float | None = 10.0

    opencode_api_key: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    openrouter_api_key: str | None = None
    gateway_custom_base_url: str | None = None
    gateway_custom_protocol: str = "openai-compatible"
    gateway_custom_api_key: str | None = None

    # --- Job sources -------------------------------------------------------
    job_sources: str = "remotive,greenhouse,lever"
    greenhouse_boards: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "github",
            "stripe",
            "airbnb",
            "lyft",
            "pinterest",
            "doordash",
            "instacart",
            "brex",
        ]
    )
    lever_companies: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "shopify",
            "deel",
            "mercury",
            "notion",
            "asana",
            "speakeasy",
            "argyle",
        ]
    )
    usajobs_api_key: str | None = None
    usajobs_email: str = "you@example.com"

    # --- Matching behaviour ------------------------------------------------
    default_limit: int = 50
    default_llm_top_n: int = 15
    default_min_score: float = 30.0

    # --- Server ------------------------------------------------------------
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    server_api_key: str | None = None
    server_rate_limit_per_min: int = 60

    # --- Output ------------------------------------------------------------
    report_dir: str = "reports"

    @field_validator("greenhouse_boards", "lever_companies", mode="before")
    @classmethod
    def _split_lists(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def job_source_ids(self) -> list[str]:
        return [part.strip() for part in self.job_sources.split(",") if part.strip()]

    def gateway_env(self) -> dict[str, str]:
        """Environment snapshot the gateway needs to resolve provider keys."""
        result = dict(os.environ)
        result.update(
            {
                "OPENCODE_API_KEY": self.opencode_api_key or "",
                "OPENAI_API_KEY": self.openai_api_key or "",
                "ANTHROPIC_API_KEY": self.anthropic_api_key or "",
                "OPENROUTER_API_KEY": self.openrouter_api_key or "",
                "GATEWAY_PROVIDER": self.gateway_provider,
                "GATEWAY_CUSTOM_BASE_URL": self.gateway_custom_base_url or "",
                "GATEWAY_CUSTOM_PROTOCOL": self.gateway_custom_protocol,
                "GATEWAY_CUSTOM_API_KEY": self.gateway_custom_api_key or "",
                "USAJOBS_API_KEY": self.usajobs_api_key or "",
            }
        )
        return result


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
