"""Protocol-agnostic message/tool types shared by all protocol clients."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from ..config import ProviderConfig
from ..usage import Usage

T = TypeVar("T")

MessageRole = Literal["system", "user", "assistant", "tool"]

EMIT_TOOL_NAME = "emit_json"


@dataclass(frozen=True)
class Message:
    role: MessageRole
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw: str = ""

    @classmethod
    def parse_arguments(cls, raw: str) -> dict[str, Any]:
        raw = raw.strip()
        try:
            return dict(json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON-schema (draft 2020-12 without $schema)


@dataclass
class ChatRequest:
    model: str
    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    tool_choice: Literal["auto", "required", "none"] = "auto"
    force_tool: str | None = None  # name of a tool the model must call
    json_mode: bool = False  # ask the provider for strict JSON via response_format when supported
    temperature: float | None = None
    max_tokens: int | None = None
    stop: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResult:
    content: str
    tool_calls: list[ToolCall]
    usage: Usage
    finish_reason: str | None
    raw: dict[str, Any]


def json_tool(
    schema: dict[str, Any], name: str = EMIT_TOOL_NAME, description: str = ""
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description or "Emit the requested structured output as JSON.",
        parameters=schema,
    )


class ProtocolClient(ABC):
    """Conversation protocol for a family of endpoints."""

    @abstractmethod
    async def chat(
        self, provider: ProviderConfig, request: ChatRequest, *, env: dict[str, str]
    ) -> ChatResult:
        """Send a non-streaming chat request and return a structured result."""

    @abstractmethod
    def chat_stream(
        self, provider: ProviderConfig, request: ChatRequest, *, env: dict[str, str]
    ) -> AsyncIterator[str]:
        """Stream text deltas from the endpoint. Usage is not returned."""
