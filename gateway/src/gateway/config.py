"""Provider configuration models.

The shape mirrors `opencode.json`'s provider block on purpose, so that a
provider configured for opencode can be reused verbatim via
``providers_from_opencode_config``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Protocol(StrEnum):
    OPENAI_COMPATIBLE = "openai-compatible"
    ANTHROPIC = "anthropic"


class ModelConfig(BaseModel):
    """Metadata for an individual model exposed by a provider."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str | None = None
    protocol: Protocol | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class ProviderConfig(BaseModel):
    """A single LLM endpoint and the models it exposes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str | None = None
    base_url: str = Field(min_length=1, max_length=512)
    protocol: Protocol = Protocol.OPENAI_COMPATIBLE
    api_key_env: str | None = Field(default=None, max_length=128)
    api_key: SecretStr | None = None
    allow_missing_key: bool = False
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: float = Field(default=60.0, gt=0, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    models: dict[str, ModelConfig] = Field(default_factory=dict)

    def resolve_key(self, *, env: dict[str, str], allow_missing: bool | None = None) -> str | None:
        """Resolve this provider's API key from its config or environment."""
        from .security import resolve_api_key

        secret = self.api_key.get_secret_value() if self.api_key else None
        return resolve_api_key(
            env=env,
            api_key=secret,
            api_key_env=self.api_key_env,
            allow_missing=allow_missing if allow_missing is not None else self.allow_missing_key,
        )

    def model(self, model_id: str) -> ModelConfig:
        return self.models.get(model_id) or ModelConfig(id=model_id)
