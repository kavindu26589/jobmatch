"""OpenAI-compatible protocol: request shaping, parsing, error mapping."""

from __future__ import annotations

import httpx
import respx

from gateway.errors import AuthenticationError, ClientError, RateLimitError, ServerError
from gateway.protocols import ChatRequest, Message, json_tool
from gateway.protocols.openai_compatible import OpenAICompatibleClient


def _request() -> ChatRequest:
    return ChatRequest(
        model="gpt-5.4-mini",
        messages=[Message(role="user", content="Hello")],
        temperature=0.2,
    )


async def test_basic_chat(zen, env) -> None:
    client = OpenAICompatibleClient()
    async with respx.mock:
        route = respx.post("https://opencode.test/zen/v1/chat/completions")
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2},
                },
            )
        )
        result = await client.chat(zen, _request(), env=env)
    assert result.content == "hi"
    assert result.usage.input_tokens == 5
    sent = route.calls[0].request
    auth = sent.headers.get("authorization")
    assert auth == "Bearer test-zen-key"
    body = sent.content
    assert b'"temperature":0.2' in body
    assert b'"model":"gpt-5.4-mini"' in body


async def test_tool_call_parsing(zen, env) -> None:
    client = OpenAICompatibleClient()
    request = ChatRequest(
        model="m",
        messages=[Message(role="user", content="x")],
        tools=[
            json_tool(
                {"type": "object", "properties": {"name": {"type": "string"}}}, description="d"
            )
        ],
        force_tool="emit_json",
    )
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
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "emit_json",
                                            "arguments": '{"name": "Ada"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4},
                },
            )
        )
        result = await client.chat(zen, request, env=env)
    assert result.tool_calls[0].name == "emit_json"
    assert result.tool_calls[0].arguments == {"name": "Ada"}
    assert result.tool_calls[0].id == "call_1"


async def test_error_mapping(zen, env) -> None:
    client = OpenAICompatibleClient()
    cases = [
        (401, AuthenticationError),
        (403, AuthenticationError),
        (429, RateLimitError),
        (400, ClientError),
        (500, ServerError),
        (503, ServerError),
    ]
    for status, expected in cases:
        async with respx.mock:
            respx.post("https://opencode.test/zen/v1/chat/completions").mock(
                return_value=httpx.Response(status, json={"error": {"message": "boom"}})
            )
            try:
                await client.chat(zen, _request(), env=env)
            except expected:
                continue
            raise AssertionError(f"expected {expected} for HTTP {status}")


async def test_retry_after_header(zen, env) -> None:
    client = OpenAICompatibleClient()
    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            return_value=httpx.Response(429, json={}, headers={"retry-after": "3"})
        )
        try:
            await client.chat(zen, _request(), env=env)
        except RateLimitError as exc:
            assert exc.retry_after == 3.0
            return
        raise AssertionError("expected RateLimitError")


async def test_network_error_mapping(zen, env) -> None:
    from gateway.errors import NetworkError

    client = OpenAICompatibleClient()
    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("refused")
        )
        try:
            await client.chat(zen, _request(), env=env)
        except NetworkError:
            return
        raise AssertionError("expected NetworkError")


async def test_stream_deltas(zen, env) -> None:
    client = OpenAICompatibleClient()
    request = ChatRequest(model="m", messages=[Message(role="user", content="hello")])
    lines = [
        'data: {"choices": [{"delta": {"content": "Hello "}}]}',
        'data: {"choices": [{"delta": {"content": "world"}}]}',
        "data: [DONE]",
    ]
    async with respx.mock:
        respx.post("https://opencode.test/zen/v1/chat/completions").mock(
            return_value=httpx.Response(
                200, text="\n".join(lines), headers={"content-type": "text/event-stream"}
            )
        )
        deltas: list[str] = []
        async for delta in client.chat_stream(zen, request, env=env):
            deltas.append(delta)
    assert "".join(deltas) == "Hello world"
