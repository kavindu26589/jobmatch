"""Anthropic Messages protocol: request shaping, tool use, parsing."""

from __future__ import annotations

import json

import httpx
import respx

from gateway.protocols import ChatRequest, Message, ToolCall, ToolSpec
from gateway.protocols.anthropic import AnthropicClient


async def test_basic_messages(anthropic, env) -> None:
    client = AnthropicClient()
    request = ChatRequest(model="claude-sonnet-4.6", messages=[Message(role="user", content="hi")])
    async with respx.mock:
        route = respx.post("https://anthropic.test/v1/messages")
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "Hello!"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 4, "output_tokens": 2, "cache_read_input_tokens": 1},
                },
            )
        )
        result = await client.chat(anthropic, request, env=env)
    assert result.content == "Hello!"
    assert result.usage.input_tokens == 4
    assert result.usage.cached_input_tokens == 1
    sent = route.calls[0].request
    assert sent.headers["x-api-key"] == "test-ant-key"
    assert sent.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(sent.content)
    assert body["max_tokens"] == 4096
    assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]


async def test_tool_use_and_results(anthropic, env) -> None:
    client = AnthropicClient()
    tool = ToolSpec(name="emit_json", description="emit", parameters={"type": "object"})
    request = ChatRequest(
        model="claude",
        messages=[
            Message(role="system", content="be strict"),
            Message(role="user", content="parse it"),
        ],
        tools=[tool],
        force_tool="emit_json",
    )
    async with respx.mock:
        route = respx.post("https://anthropic.test/v1/messages")
        route.mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "emit_json",
                            "input": {"x": 1},
                        }
                    ],
                    "stop_reason": "tool_use",
                    "usage": {"input_tokens": 5, "output_tokens": 3},
                },
            )
        )
        result = await client.chat(anthropic, request, env=env)
    body = json.loads(route.calls[0].request.content)
    assert body["system"] == "be strict"
    assert body["tool_choice"] == {"type": "tool", "name": "emit_json"}
    assert result.tool_calls[0].name == "emit_json"
    assert result.tool_calls[0].arguments == {"x": 1}

    followup = ChatRequest(
        model="claude",
        messages=[
            Message(role="user", content="parsed"),
            Message(role="assistant", tool_calls=(result.tool_calls[0],)),
            Message(role="tool", tool_call_id="toolu_1", content='{"ok": true}'),
        ],
        tools=[tool],
    )
    async with respx.mock:
        route2 = respx.post("https://anthropic.test/v1/messages")
        route2.mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "done"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 9, "output_tokens": 1},
                },
            )
        )
        await client.chat(anthropic, followup, env=env)
    body2 = json.loads(route2.calls[0].request.content)
    assistant = body2["messages"][1]
    assert any(block["type"] == "tool_use" for block in assistant["content"])
    tool_msg = body2["messages"][2]
    assert tool_msg["role"] == "user"
    assert tool_msg["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": '{"ok": true}',
    }


async def test_status_mapping(anthropic, env) -> None:
    from gateway.errors import RateLimitError

    client = AnthropicClient()
    async with respx.mock:
        respx.post("https://anthropic.test/v1/messages").mock(
            return_value=httpx.Response(429, json={})
        )
        try:
            await client.chat(anthropic, ChatRequest(model="m", messages=[]), env=env)
        except RateLimitError:
            return
        raise AssertionError("expected RateLimitError")


async def test_stream_deltas(anthropic, env) -> None:
    client = AnthropicClient()
    request = ChatRequest(model="claude", messages=[Message(role="user", content="hi")])
    lines = [
        'event: message_start\ndata: {"type":"message_start","message":{"usage":{}}}\r\n',
        (
            "event: content_block_delta\n"
            'data: {"type":"content_block_delta","delta":{"type":"text_delta",'
            '"text":"Hi "}}\r\n'
        ),
        (
            "event: content_block_delta\n"
            'data: {"type":"content_block_delta","delta":{"type":"text_delta",'
            '"text":"there"}}\r\n'
        ),
        'event: message_stop\ndata: {"type":"message_stop"}\r\n',
    ]
    async with respx.mock:
        respx.post("https://anthropic.test/v1/messages").mock(
            return_value=httpx.Response(
                200, text="".join(lines), headers={"content-type": "text/event-stream"}
            )
        )
        deltas: list[str] = []
        async for delta in client.chat_stream(anthropic, request, env=env):
            deltas.append(delta)
    assert "".join(deltas) == "Hi there"
