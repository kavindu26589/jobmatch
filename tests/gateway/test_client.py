"""LLMGateway: retry policy, structured output, budget guard."""

from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import BaseModel

from gateway import LLMGateway, ProviderRegistry, UsageLedger
from gateway.config import Protocol, ProviderConfig
from gateway.errors import MaxRetriesExceeded, NetworkError, ProtocolError
from gateway.providers import ProviderRegistry as Registry


class Person(BaseModel):
    name: str
    years_python: int


def make_gateway(*, registry: Registry | None = None, **kwargs) -> LLMGateway:
    reg = registry or ProviderRegistry()
    if registry is None:
        reg.register(
            ProviderConfig(
                id="zen",
                base_url="https://opencode.test/zen/v1",
                protocol=Protocol.OPENAI_COMPATIBLE,
                api_key_env="OPENCODE_API_KEY",
            )
        )
    return LLMGateway(reg, env={"OPENCODE_API_KEY": "k"}, **kwargs)


def _chat_json(payload: dict) -> dict:
    return {
        "choices": [{"message": {"content": None}, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }


async def test_structured_via_tool() -> None:
    gateway = make_gateway()
    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "type": "function",
                                        "function": {
                                            "name": "emit_json",
                                            "arguments": '{"name": "Ada", "years_python": 5}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                },
            )
        )
        person = await gateway.structured(
            "zen", "gpt-5.4-mini", system="extract", user="Ada, 5y python", schema=Person
        )
    assert person.name == "Ada"
    assert person.years_python == 5


async def test_structured_falls_back_to_content_json() -> None:
    gateway = make_gateway()
    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": '{"name":"Bob","years_python":0}',
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 4},
                },
            )
        )
        person = await gateway.structured("zen", "m", user="Bob", schema=Person)
    assert person.name == "Bob"


async def test_retries_then_succeeds() -> None:
    gateway = make_gateway()
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(side_effect=handler)
        result = await gateway.complete("zen", "m", "hi")
    assert result == "ok"
    assert call_count == 3


async def test_retries_exhausted() -> None:
    gateway = make_gateway()
    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            return_value=httpx.Response(503, json={"error": "down"})
        )
        with pytest.raises(MaxRetriesExceeded):
            await gateway.complete("zen", "m", "hi")


async def test_auth_error_not_retried() -> None:
    from gateway.errors import AuthenticationError

    gateway = make_gateway()
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, json={"error": "no"})

    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(side_effect=handler)
        with pytest.raises(AuthenticationError):
            await gateway.complete("zen", "m", "hi")
    assert call_count == 1


async def test_budget_blocks_requests() -> None:
    ledger = UsageLedger(budget_usd=0.0)
    gateway = make_gateway(ledger=ledger)
    from gateway.errors import BudgetExceeded

    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=_chat_json({}))
        )
        with pytest.raises(BudgetExceeded):
            await gateway.complete("zen", "m", "hi")


async def test_usage_recorded() -> None:
    gateway = make_gateway()
    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 200},
                },
            )
        )
        await gateway.complete("zen", "gpt-5.4-mini", "hi")
    records = gateway.usage_snapshot()
    assert len(records) == 1
    assert records[0].usage.input_tokens == 100


async def test_circuit_breaker_opens() -> None:
    from gateway import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=2, reset_after=60)
    gateway = make_gateway(breaker=breaker)
    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            return_value=httpx.Response(500, json={"error": "x"})
        )
        # First logical request trips the breaker while retrying -> fail fast.
        with pytest.raises(NetworkError):
            await gateway.complete("zen", "m", "hi")
        # During the first request the breaker tripped after 2 failures and
        # the loop failed fast; the second logical request never hit the wire.
        before = len(respx.calls)
        with pytest.raises(NetworkError):
            await gateway.complete("zen", "m", "hi")
        assert len(respx.calls) == before


async def test_structured_schema_mismatch_raises() -> None:
    gateway = make_gateway()
    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "type": "function",
                                        "function": {
                                            "name": "emit_json",
                                            "arguments": '{"nope": true}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        )
        with pytest.raises(ProtocolError):
            await gateway.structured("zen", "m", user="x", schema=Person)


def test_sync_wrappers() -> None:
    gateway = make_gateway()
    with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "sync hi"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        )
        assert gateway.complete_sync("zen", "m", "hi") == "sync hi"
