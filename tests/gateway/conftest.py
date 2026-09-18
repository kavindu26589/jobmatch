"""Shared fixtures for gateway tests."""

from __future__ import annotations

import pytest

from gateway.config import Protocol, ProviderConfig


@pytest.fixture
def zen() -> ProviderConfig:
    return ProviderConfig(
        id="zen",
        base_url="https://opencode.test/zen/v1",
        protocol=Protocol.OPENAI_COMPATIBLE,
        api_key_env="OPENCODE_API_KEY",
    )


@pytest.fixture
def anthropic() -> ProviderConfig:
    return ProviderConfig(
        id="anthropic",
        base_url="https://anthropic.test/v1",
        protocol=Protocol.ANTHROPIC,
        api_key_env="ANTHROPIC_API_KEY",
    )


@pytest.fixture
def env() -> dict[str, str]:
    return {
        "OPENCODE_API_KEY": "test-zen-key",
        "ANTHROPIC_API_KEY": "test-ant-key",
        "OPENAI_API_KEY": "test-openai-key",
    }
