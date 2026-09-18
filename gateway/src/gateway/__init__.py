"""opencode-gateway: a provider-agnostic LLM client for opencode-compatible keys.

Public surface:
- :class:`~gateway.client.LLMGateway` — retrying, budgeted chat client.
- :class:`~gateway.providers.ProviderRegistry` / :func:`~gateway.providers.build_registry`
- :func:`~gateway.providers.providers_from_opencode_config` — load opencode.json providers.
- :class:`~gateway.config.ProviderConfig` — provider configuration.

Example::

    from gateway import LLMGateway, build_registry

    gateway = LLMGateway(build_registry())
    text = await gateway.complete("zen", "gpt-5.4-mini", "Hello")
"""

from .client import AsyncRateLimiter, CallOptions, CircuitBreaker, LLMGateway
from .config import ModelConfig, Protocol, ProviderConfig
from .errors import (
    AuthenticationError,
    BudgetExceeded,
    ClientError,
    ConfigurationError,
    GatewayError,
    MaxRetriesExceeded,
    NetworkError,
    ProtocolError,
    RateLimitError,
    ServerError,
)
from .providers import (
    ProviderRegistry,
    build_registry,
    providers_from_opencode_config,
    providers_from_opencode_file,
)
from .security import redact
from .usage import CostTable, Usage, UsageLedger, UsageRecord, pricing_for

__version__ = "0.1.0"

__all__ = [
    "AsyncRateLimiter",
    "AuthenticationError",
    "BudgetExceeded",
    "CallOptions",
    "CircuitBreaker",
    "ClientError",
    "ConfigurationError",
    "CostTable",
    "GatewayError",
    "LLMGateway",
    "MaxRetriesExceeded",
    "ModelConfig",
    "NetworkError",
    "Protocol",
    "ProtocolError",
    "ProviderConfig",
    "ProviderRegistry",
    "RateLimitError",
    "ServerError",
    "Usage",
    "UsageLedger",
    "UsageRecord",
    "build_registry",
    "pricing_for",
    "providers_from_opencode_config",
    "providers_from_opencode_file",
    "redact",
]
