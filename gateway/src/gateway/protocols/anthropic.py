"""Anthropic Messages protocol (``/v1/messages``).

Used for OpenCode Zen's Anthropic-compatible routes and the Anthropic API.
Tool results use Anthropic's ``tool_result`` content blocks inside a ``user``
message.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..config import ProviderConfig
from ..errors import GatewayError, NetworkError, ProtocolError, map_status
from ..security import redact
from ..usage import Usage
from .base import ChatRequest, ChatResult, Message, ProtocolClient, ToolCall

_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096


def _headers(provider: ProviderConfig, api_key: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "anthropic-version": _ANTHROPIC_VERSION,
        **provider.headers,
    }
    if api_key:
        headers["x-api-key"] = api_key
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _content_blocks(message: Message) -> list[dict[str, Any]]:
    if message.role == "tool":
        return [
            {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id or "",
                "content": message.content or "",
            }
        ]
    if message.tool_calls:
        blocks: list[dict[str, Any]] = []
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        for call in message.tool_calls:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": call.id or f"toolu_{call.name}",
                    "name": call.name,
                    "input": call.arguments,
                }
            )
        return blocks
    return [{"type": "text", "text": message.content}]


def _build_payload(request: ChatRequest) -> dict[str, Any]:
    system_parts: list[str] = []
    messages: list[Message] = []
    for message in request.messages:
        if message.role == "system":
            system_parts.append(message.content)
        else:
            messages.append(message)

    payload: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens or _DEFAULT_MAX_TOKENS,
        "messages": [
            {
                "role": "user" if message.role == "tool" else message.role,
                "content": _content_blocks(message),
            }
            for message in messages
        ],
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if request.tools:
        payload["tools"] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in request.tools
        ]
        if request.force_tool:
            payload["tool_choice"] = {"type": "tool", "name": request.force_tool}
        elif request.tool_choice == "required":
            payload["tool_choice"] = {"type": "any"}
        elif request.tool_choice == "none":
            payload["tool_choice"] = {"type": "none"}
        else:
            payload["tool_choice"] = {"type": "auto"}
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.stop:
        payload["stop_sequences"] = request.stop
    payload.update(request.extra)
    return payload


def _parse_usage(raw: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        cached_input_tokens=int(
            raw.get("cache_read_input_tokens") or raw.get("cache_creation_input_tokens") or 0
        ),
    )


def _parse_chat_result(raw: dict[str, Any], request: ChatRequest) -> ChatResult:
    try:
        content = ""
        tool_calls: list[ToolCall] = []
        for block in raw.get("content") or []:
            block_type = block.get("type")
            if block_type == "text":
                content += block.get("text") or ""
            elif block_type == "tool_use":
                raw_args = block.get("input") or {}
                arguments = raw_args if isinstance(raw_args, dict) else {"value": raw_args}
                tool_calls.append(
                    ToolCall(
                        id=block.get("id") or "",
                        name=block.get("name") or "",
                        arguments=arguments,
                        raw=json.dumps(arguments, ensure_ascii=False),
                    )
                )
        stop_reason = raw.get("stop_reason")
        return ChatResult(
            content=content,
            tool_calls=tool_calls,
            usage=_parse_usage(raw.get("usage") or {}),
            finish_reason=stop_reason,
            raw=raw,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"malformed anthropic messages response: {exc}") from exc


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    body = response.text[:500]
    if response.status_code >= 400:
        retry_after: float | None = None
        value = response.headers.get("retry-after")
        if value:
            try:
                retry_after = max(0.0, float(value))
            except (TypeError, ValueError):
                retry_after = None
        raise map_status(
            response.status_code,
            f"anthropic endpoint returned HTTP {response.status_code}: {redact(body)}",
            retry_after=retry_after,
        )
    raise ProtocolError(f"unexpected HTTP {response.status_code}: {redact(body)}")


def _wrap_transport(exc: Exception) -> GatewayError:
    if isinstance(exc, httpx.TimeoutException):
        return NetworkError(f"request timed out: {exc}")
    if isinstance(exc, httpx.TransportError):
        return NetworkError(f"transport error: {exc}")
    return ProtocolError(f"unexpected error: {exc}")


class AnthropicClient(ProtocolClient):
    """Implements :class:`ProtocolClient` for the Anthropic Messages API."""

    async def chat(
        self, provider: ProviderConfig, request: ChatRequest, *, env: dict[str, str]
    ) -> ChatResult:
        api_key = provider.resolve_key(env=env)
        endpoint = provider.base_url.rstrip("/") + "/messages"
        payload = _build_payload(request)
        async with httpx.AsyncClient(
            timeout=provider.timeout, headers=_headers(provider, api_key)
        ) as client:
            try:
                response = await client.post(endpoint, json=payload)
            except httpx.HTTPError as exc:
                raise _wrap_transport(exc) from exc
            _raise_for_status(response)
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise ProtocolError(f"non-JSON response from {endpoint}") from exc
            return _parse_chat_result(data, request)

    async def chat_stream(
        self, provider: ProviderConfig, request: ChatRequest, *, env: dict[str, str]
    ) -> AsyncIterator[str]:
        api_key = provider.resolve_key(env=env)
        endpoint = provider.base_url.rstrip("/") + "/messages"
        payload = _build_payload(request)
        payload["stream"] = True
        headers = {**_headers(provider, api_key), "Accept": "text/event-stream"}
        async with httpx.AsyncClient(timeout=provider.timeout, headers=headers) as client:
            try:
                async with client.stream("POST", endpoint, json=payload) as response:
                    if not response.is_success:
                        body = (await response.aread()).decode("utf-8", errors="replace")[:500]
                        raise map_status(
                            response.status_code,
                            f"streaming request failed HTTP {response.status_code}: {redact(body)}",
                        )
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta") or {}
                            text = delta.get("text")
                            if text:
                                yield str(text)
                        elif event.get("type") == "error":
                            error = event.get("error") or {}
                            raise ServerStreamError(
                                str(error.get("message", "unknown stream error"))
                            )
            except httpx.HTTPError as exc:
                raise _wrap_transport(exc) from exc


class ServerStreamError(ProtocolError):
    pass
