"""Protocol clients. Pick one per :class:`gateway.config.Protocol`."""

from ..config import Protocol
from .anthropic import AnthropicClient
from .base import (
    EMIT_TOOL_NAME,
    ChatRequest,
    ChatResult,
    Message,
    ProtocolClient,
    ToolCall,
    ToolSpec,
    json_tool,
)
from .openai_compatible import OpenAICompatibleClient

__all__ = [
    "EMIT_TOOL_NAME",
    "AnthropicClient",
    "ChatRequest",
    "ChatResult",
    "Message",
    "OpenAICompatibleClient",
    "ProtocolClient",
    "ToolCall",
    "ToolSpec",
    "json_tool",
]


def build_protocol_client(protocol: Protocol) -> ProtocolClient:
    """Return the protocol client for ``protocol``."""
    if protocol is Protocol.OPENAI_COMPATIBLE:
        return OpenAICompatibleClient()
    if protocol is Protocol.ANTHROPIC:
        return AnthropicClient()
    raise ValueError(f"unsupported protocol: {protocol}")
