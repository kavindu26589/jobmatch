"""OpenAI chat-completions compatible protocol.

Used by OpenCode Zen's ``/v1/chat/completions`` route, OpenAI, OpenRouter,
Ollama, local vLLM servers, and any compatible gateway.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..config import Protocol, ProviderConfig
from ..errors import GatewayError, NetworkError, ProtocolError, map_status
from ..security import redact
from ..usage import Usage
from .base import (
    ChatRequest,
    ChatResult,
    Message,
    ProtocolClient,
    ToolCall,
    ToolSpec,
)

_STREAM_CLOSE_HINTS = {"[DONE]", "data: [DONE]", "[DONE]\r"}


def _headers(provider: ProviderConfig, api_key: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json", **provider.headers}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _tool_payload(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _messages_payload(messages: list[Message]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            payload.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id or "",
                    "content": message.content,
                }
            )
            continue
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.raw or json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        payload.append(item)
    return payload


def _build_payload(request: ChatRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": _messages_payload(request.messages),
        "stream": False,
    }
    if request.tools:
        payload["tools"] = [_tool_payload(tool) for tool in request.tools]
        if request.force_tool:
            payload["tool_choice"] = {"type": "function", "function": {"name": request.force_tool}}
        else:
            payload["tool_choice"] = request.tool_choice
    if request.json_mode and not request.tools:
        payload["response_format"] = {"type": "json_object"}
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.stop:
        payload["stop"] = request.stop
    payload.update(request.extra)
    return payload


def _parse_usage(raw: dict[str, Any]) -> Usage:
    details = raw.get("prompt_tokens_details") or {}
    return Usage(
        input_tokens=int(raw.get("prompt_tokens") or 0),
        output_tokens=int(raw.get("completion_tokens") or 0),
        cached_input_tokens=int(details.get("cached_tokens") or 0),
    )


def _parse_chat_result(raw: dict[str, Any], request: ChatRequest) -> ChatResult:
    try:
        choices = list(raw.get("choices") or [])
        choice = choices[0] if choices else {}
        message = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")
        content = message.get("content") or ""
        tool_calls: list[ToolCall] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw_args = function.get("arguments") or "{}"
            args = ToolCall.parse_arguments(raw_args)
            tool_calls.append(
                ToolCall(
                    id=call.get("id") or "",
                    name=function.get("name") or "",
                    arguments=args,
                    raw=raw_args,
                )
            )
        return ChatResult(
            content=str(content),
            tool_calls=tool_calls,
            usage=_parse_usage(raw.get("usage") or {}),
            finish_reason=finish_reason,
            raw=raw,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"malformed chat.completions response: {exc}") from exc


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    body = response.text[:500]
    if response.status_code >= 400:
        raise map_status(
            response.status_code,
            (
                f"{Protocol.OPENAI_COMPATIBLE.value} endpoint returned "
                f"HTTP {response.status_code}: {redact(body)}"
            ),
            retry_after=_retry_after(response),
        )
    raise ProtocolError(f"unexpected HTTP {response.status_code}: {redact(body)}")


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _wrap_transport(exc: Exception) -> GatewayError:
    if isinstance(exc, httpx.TimeoutException):
        return NetworkError(f"request timed out: {exc}")
    if isinstance(exc, httpx.TransportError):
        return NetworkError(f"transport error: {exc}")
    return ProtocolError(f"unexpected error: {exc}")


class OpenAICompatibleClient(ProtocolClient):
    """Implements :class:`ProtocolClient` for chat/completions endpoints."""

    async def chat(
        self, provider: ProviderConfig, request: ChatRequest, *, env: dict[str, str]
    ) -> ChatResult:
        api_key = provider.resolve_key(env=env)
        endpoint = provider.base_url.rstrip("/") + "/chat/completions"
        payload = _build_payload(request)
        headers = _headers(provider, api_key)

        async with httpx.AsyncClient(timeout=provider.timeout, headers=headers) as client:
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
        endpoint = provider.base_url.rstrip("/") + "/chat/completions"
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
                            retry_after=_retry_after(response),
                        )
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or line in _STREAM_CLOSE_HINTS:
                            continue
                        if not line.startswith("data:"):
                            continue
                        try:
                            chunk = json.loads(line[5:].strip())
                        except json.JSONDecodeError:
                            continue
                        deltas: list[str] = []
                        for choice in chunk.get("choices") or []:
                            delta = choice.get("delta") or {}
                            piece = delta.get("content")
                            if piece:
                                deltas.append(str(piece))
                        if deltas:
                            yield "".join(deltas)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise _wrap_transport(exc) from exc
