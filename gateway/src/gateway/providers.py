"""Provider registry, built-in presets, and opencode.json compatibility.

The headline feature here: ``providers_from_opencode_config`` ingests the
``providers`` block of an existing `opencode.json` (v2 ``settings`` shape or v1
``options``/``npm`` shape) so the same base URL, key, headers, and models that
opencode uses can be driven through this gateway unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .config import ModelConfig, Protocol, ProviderConfig
from .errors import ConfigurationError
from .security import parse_env_key


def builtin_zen() -> ProviderConfig:
    """OpenCode Zen: the curated model gateway used by default."""
    models: dict[str, ModelConfig] = {}
    for model_id, (name, ctx, out) in _ZEN_MODEL_CATALOG.items():
        models[model_id] = ModelConfig(
            id=model_id,
            name=name,
            context_window=ctx,
            max_output_tokens=out,
        )
    return ProviderConfig(
        id="zen",
        name="OpenCode Zen",
        base_url="https://opencode.ai/zen/v1",
        protocol=Protocol.OPENAI_COMPATIBLE,
        api_key_env="OPENCODE_API_KEY",
        models=models,
    )


_ZEN_MODEL_CATALOG: dict[str, tuple[str, int, int]] = {
    # OpenAI-compatible (chat/completions + responses)
    "gpt-5.4-mini": ("GPT 5.4 Mini", 272000, 32768),
    "gpt-5.4-nano": ("GPT 5.4 Nano", 272000, 32768),
    "gpt-5.3-codex": ("GPT 5.3 Codex", 160000, 64000),
    "gpt-5.2": ("GPT 5.2", 272000, 32768),
    "gpt-5.1": ("GPT 5.1", 272000, 32768),
    "gpt-5": ("GPT 5", 272000, 32768),
    "gpt-5-nano": ("GPT 5 Nano", 272000, 32768),
    "grok-4.6": ("Grok 4.6", 256000, 32768),
    "muse-spark-1.3": ("Muse Spark 1.3", 256000, 32768),
    # Anthropic-compatible
    "claude-opus-5": ("Claude Opus 5", 200000, 32768),
    "claude-sonnet-5": ("Claude Sonnet 5", 200000, 32768),
    "claude-sonnet-4.6": ("Claude Sonnet 4.6", 200000, 32768),
    "claude-haiku-4.5": ("Claude Haiku 4.5", 200000, 32768),
    "claude-fable-5.1": ("Claude Fable 5.1", 200000, 32768),
    "qwen3.7-max": ("Qwen 3.7 Max", 256000, 32768),
    # OpenAI-compatible open models via Zen
    "deepseek-v4-flash": ("DeepSeek V4 Flash", 128000, 16384),
    "deepseek-v4-pro": ("DeepSeek V4 Pro", 128000, 16384),
    "glm-5.3": ("GLM 5.3", 128000, 16384),
    "glm-5.3-flash": ("GLM 5.3 Flash", 128000, 16384),
    "kimi-k2.6": ("Kimi K2.6", 128000, 16384),
    # Gemini via Zen
    "gemini-3.7-flash": ("Gemini 3.7 Flash", 1024000, 8192),
    "gemini-3.5-flash": ("Gemini 3.5 Flash", 1024000, 8192),
}


def provider_from_opencode_entry(provider_id: str, entry: Mapping[str, Any]) -> ProviderConfig:
    """Load a single opencode provider entry (v1 or v2 shape)."""
    settings = dict(entry.get("settings") or entry.get("options") or {})
    package = str(entry.get("package") or entry.get("npm") or "")
    env_list = list(entry.get("env") or [])

    base_url = settings.get("baseURL") or settings.get("base_url")
    if not base_url:
        raise ConfigurationError(f"provider '{provider_id}' in opencode config has no baseURL")

    protocol_value = settings.get("protocol")
    if protocol_value:
        protocol = Protocol(protocol_value)
    elif "anthropic" in package:
        protocol = Protocol.ANTHROPIC
    else:
        protocol = Protocol.OPENAI_COMPATIBLE

    api_key: str | None = None
    api_key_env: str | None = None
    raw_key = settings.get("apiKey") or settings.get("api_key")
    if raw_key:
        api_key, api_key_env = parse_env_key(str(raw_key))
    if api_key_env is None and not api_key and env_list:
        api_key_env = env_list[0]

    models: dict[str, ModelConfig] = {}
    for model_id, spec in (entry.get("models") or {}).items():
        if not isinstance(spec, dict) or model_id == "$default":
            continue
        limits = spec.get("limit") or {}
        models[model_id] = ModelConfig(
            id=model_id,
            name=spec.get("name"),
            context_window=limits.get("context") if isinstance(limits, dict) else None,
            max_output_tokens=limits.get("output") if isinstance(limits, dict) else None,
            headers=dict(spec.get("headers") or {}),
            options=dict(spec.get("options") or {}),
        )

    return ProviderConfig(
        id=provider_id,
        name=entry.get("name") or provider_id,
        base_url=str(base_url).rstrip("/"),
        protocol=protocol,
        api_key_env=api_key_env,
        api_key=api_key,
        headers=dict(settings.get("headers") or {}),
        timeout=float(settings.get("timeout") or settings.get("timeoutMs") or 60) / 1000
        if settings.get("timeoutMs")
        else float(settings.get("timeout") or 60.0),
        max_retries=int(settings.get("maxRetries") or 3),
        models=models,
    )


def providers_from_opencode_config(config: Mapping[str, Any]) -> list[ProviderConfig]:
    """Parse the provider block of an ``opencode.json`` document."""
    providers = config.get("providers") if isinstance(config, dict) else None
    if providers is None and isinstance(config, dict):
        providers = config.get("provider")
    if not isinstance(providers, dict):
        raise ConfigurationError("opencode config has no 'providers' object")
    result: list[ProviderConfig] = []
    for provider_id, entry in providers.items():
        if not isinstance(entry, dict):
            raise ConfigurationError(f"provider '{provider_id}' is not a dict")
        result.append(provider_from_opencode_entry(str(provider_id), entry))
    return result


def providers_from_opencode_file(path: str | Path) -> list[ProviderConfig]:
    """Load providers from an ``opencode.json`` / ``opencode.jsonc`` file."""
    target = Path(path)
    raw = target.read_text(encoding="utf-8")
    if target.suffix == ".jsonc" or raw.lstrip().startswith("//"):
        import re

        raw = re.sub(r"^\s*//.*$", "", raw, flags=re.MULTILINE)
    return providers_from_opencode_config(json.loads(raw))


def register_from_opencode_config(
    registry: ProviderRegistry, config: Mapping[str, Any], *, replace: bool = True
) -> None:
    for provider_config in providers_from_opencode_config(config):
        registry.register(provider_config, replace=replace)


_BUILTIN_PROVIDERS: dict[str, ProviderConfig] = {
    "zen": builtin_zen(),
    "openai": ProviderConfig(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        protocol=Protocol.OPENAI_COMPATIBLE,
        api_key_env="OPENAI_API_KEY",
    ),
    "anthropic": ProviderConfig(
        id="anthropic",
        name="Anthropic",
        base_url="https://api.anthropic.com/v1",
        protocol=Protocol.ANTHROPIC,
        api_key_env="ANTHROPIC_API_KEY",
    ),
    "openrouter": ProviderConfig(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        protocol=Protocol.OPENAI_COMPATIBLE,
        api_key_env="OPENROUTER_API_KEY",
    ),
    "ollama": ProviderConfig(
        id="ollama",
        name="Ollama (local)",
        base_url="http://127.0.0.1:11434/v1",
        protocol=Protocol.OPENAI_COMPATIBLE,
        api_key=None,
        allow_missing_key=True,
        timeout=300.0,
    ),
}


class ProviderRegistry:
    """Named collection of :class:`ProviderConfig` objects."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderConfig] = {}

    def register(self, config: ProviderConfig, *, replace: bool = True) -> None:
        existing = config.id in self._providers
        if existing and not replace:
            raise ConfigurationError(f"provider '{config.id}' already registered")
        self._providers[config.id] = config

    def register_many(self, configs: list[ProviderConfig], *, replace: bool = True) -> None:
        for config in configs:
            self.register(config, replace=replace)

    def register_builtins(self) -> ProviderRegistry:
        for config in _BUILTIN_PROVIDERS.values():
            self.register(config)
        return self

    def get(self, provider_id: str) -> ProviderConfig:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ConfigurationError(f"unknown provider '{provider_id}'")
        return provider

    def ids(self) -> list[str]:
        return sorted(self._providers)

    def split_model(self, model_ref: str) -> tuple[str, str]:
        """Split ``"provider/model"`` into (provider_id, model_id)."""
        if "/" in model_ref:
            provider_id, _, model_id = model_ref.partition("/")
            if provider_id in self._providers:
                return provider_id, model_id
        default = "zen" if "zen" in self._providers else next(iter(self._providers), "zen")
        return default, model_ref

    def __len__(self) -> int:
        return len(self._providers)

    def __contains__(self, provider_id: str) -> bool:
        return provider_id in self._providers


def build_registry(
    *,
    env: Mapping[str, str] | None = None,
    opencode_config: Mapping[str, Any] | None = None,
) -> ProviderRegistry:
    """Construct a registry from built-ins plus an optional opencode config."""
    registry = ProviderRegistry().register_builtins()
    if opencode_config:
        register_from_opencode_config(registry, opencode_config)
    if env is None:
        return registry
    # Optional env-driven custom provider (used by the app layer).
    provider_name = env.get("GATEWAY_PROVIDER", "zen")
    if provider_name == "custom":
        base_url = env.get("GATEWAY_CUSTOM_BASE_URL", "").rstrip("/")
        if not base_url:
            raise ConfigurationError(
                "GATEWAY_CUSTOM_PROVIDER=custom requires GATEWAY_CUSTOM_BASE_URL"
            )
        protocol = Protocol(env.get("GATEWAY_CUSTOM_PROTOCOL", Protocol.OPENAI_COMPATIBLE.value))
        registry.register(
            ProviderConfig(
                id="custom",
                name="Custom provider",
                base_url=base_url,
                protocol=protocol,
                api_key_env="GATEWAY_CUSTOM_API_KEY",
                allow_missing_key=True,
            )
        )
    return registry
