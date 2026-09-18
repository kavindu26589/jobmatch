"""Registry, built-ins, and opencode.json compatibility."""

from __future__ import annotations

import json

import pytest

from gateway.config import Protocol
from gateway.errors import ConfigurationError
from gateway.providers import (
    ProviderRegistry,
    build_registry,
    providers_from_opencode_config,
    providers_from_opencode_file,
)


def test_builtins_registered() -> None:
    registry = ProviderRegistry().register_builtins()
    assert "zen" in registry
    assert "openai" in registry
    assert "anthropic" in registry
    zen = registry.get("zen")
    assert zen.base_url == "https://opencode.ai/zen/v1"
    assert zen.protocol is Protocol.OPENAI_COMPATIBLE
    assert zen.api_key_env == "OPENCODE_API_KEY"


def test_register_duplicate_rejected() -> None:
    registry = ProviderRegistry()
    registry.register(build_registry().get("zen"))
    with pytest.raises(ConfigurationError):
        registry.register(build_registry().get("zen"), replace=False)


def test_unknown_provider_raises() -> None:
    registry = ProviderRegistry()
    with pytest.raises(ConfigurationError):
        registry.get("nope")


def test_split_model() -> None:
    registry = ProviderRegistry().register_builtins()
    assert registry.split_model("zen/gpt-5") == ("zen", "gpt-5")
    assert registry.split_model("gpt-5") == ("zen", "gpt-5")


def test_providers_from_opencode_config_v2() -> None:
    config = {
        "providers": {
            "acme": {
                "name": "Acme Gateway",
                "env": ["ACME_API_KEY"],
                "package": "@opencode-ai/ai/providers/openai-compatible",
                "settings": {
                    "baseURL": "https://llm.acme.example/v1",
                    "apiKey": "{env:ACME_API_KEY}",
                    "headers": {"X-Tenant": "eng"},
                },
                "models": {
                    "qwen3-coder": {
                        "name": "Qwen 3 Coder",
                        "limit": {"context": 131072, "output": 32768},
                    }
                },
            },
            "anthropic-proxy": {
                "package": "@opencode-ai/ai/providers/anthropic",
                "settings": {
                    "baseURL": "https://proxy.example/anthropic",
                    "apiKey": "sk-ant-abc123",
                },
            },
        }
    }
    providers = providers_from_opencode_config(config)
    by_id = {p.id: p for p in providers}
    acme = by_id["acme"]
    assert acme.base_url == "https://llm.acme.example/v1"
    assert acme.api_key_env == "ACME_API_KEY"
    assert acme.headers["X-Tenant"] == "eng"
    assert acme.protocol is Protocol.OPENAI_COMPATIBLE
    assert acme.model("qwen3-coder").context_window == 131072
    proxy = by_id["anthropic-proxy"]
    assert proxy.protocol is Protocol.ANTHROPIC
    assert proxy.api_key.get_secret_value() == "sk-ant-abc123"


def test_providers_from_opencode_config_v1() -> None:
    config = {
        "provider": {
            "ollama": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": "http://127.0.0.1:11434/v1"},
                "models": {"gemma-3": {}},
            }
        }
    }
    providers = providers_from_opencode_config(config)
    assert providers[0].id == "ollama"
    assert providers[0].base_url == "http://127.0.0.1:11434/v1"
    assert providers[0].api_key_env is None
    assert providers[0].api_key is None


def test_providers_from_opencode_config_invalid() -> None:
    with pytest.raises(ConfigurationError):
        providers_from_opencode_config({"providers": "nope"})
    with pytest.raises(ConfigurationError):
        providers_from_opencode_config({"providers": {"x": {"settings": {}}}})


def test_providers_from_opencode_file(tmp_path) -> None:
    sample = {
        "providers": {
            "gate": {
                "package": "@opencode-ai/ai/providers/openai-compatible",
                "settings": {"baseURL": "https://gate.example/v1", "apiKey": "{env:GATE_KEY}"},
            }
        }
    }
    path = tmp_path / "opencode.json"
    path.write_text(json.dumps(sample), encoding="utf-8")
    providers = providers_from_opencode_file(path)
    assert providers[0].api_key_env == "GATE_KEY"


def test_build_registry_merges_opencode_providers() -> None:
    config = {
        "providers": {
            "acme": {
                "package": "@opencode-ai/ai/providers/openai-compatible",
                "settings": {"baseURL": "https://acme.example/v1"},
            }
        }
    }
    registry = build_registry(opencode_config=config)
    assert "acme" in registry
    assert "zen" in registry
