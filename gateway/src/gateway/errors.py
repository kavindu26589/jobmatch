"""Error taxonomy for the gateway.

Errors are split into *retryable* (transport, 429, 5xx) and *non-retryable*
(auth, malformed payloads, provider contract violations). The client layer
uses :func:`is_retryable` to drive its retry policy.
"""

from __future__ import annotations

from typing import Any


class GatewayError(Exception):
    """Base class for all gateway errors."""

    status_code: int | None = None

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": type(self).__name__,
            "message": str(self),
            "status_code": self.status_code,
            "retry_after": self.retry_after,
        }


class ConfigurationError(GatewayError):
    """Missing or invalid gateway/provider configuration."""


class AuthenticationError(GatewayError):
    """The provider rejected the supplied credentials (HTTP 401/403)."""


class RateLimitError(GatewayError):
    """The provider rate-limited the request (HTTP 429 with retry-after)."""


class ServerError(GatewayError):
    """The provider returned a 5xx response."""


class ClientError(GatewayError):
    """The provider rejected the request payload (HTTP 4xx, non-auth)."""


class NetworkError(GatewayError):
    """Transport-level failure (DNS, connect, read/connect timeouts)."""


class ProtocolError(GatewayError):
    """The provider response could not be parsed into the expected shape."""


class BudgetExceeded(GatewayError):
    """The configured spend limit was reached."""

    def __init__(self, limit_usd: float, spent_usd: float) -> None:
        super().__init__(f"Spend budget exceeded: {spent_usd:.4f} USD >= {limit_usd:.4f} USD")
        self.limit_usd = limit_usd
        self.spent_usd = spent_usd


class MaxRetriesExceeded(GatewayError):
    """The request failed after exhausting all retry attempts."""

    def __init__(self, message: str, attempts: int, errors: list[GatewayError]) -> None:
        tail = ", ".join(str(e) for e in errors[-3:])
        super().__init__(f"{message} after {attempts} attempt(s); latest errors: {tail}")
        self.attempts = attempts
        self.errors = errors


_SERVER_RETRY_STATUSES = frozenset({408, 425, 429, *range(500, 600)})


def is_retryable(error: Exception) -> bool:
    """Whether a failure should be retried with backoff."""
    if isinstance(error, TimeoutError | NetworkError | RateLimitError | ServerError):
        return True
    status_code = getattr(error, "status_code", None)
    return isinstance(status_code, int) and status_code in _SERVER_RETRY_STATUSES


def map_status(status_code: int, message: str, *, retry_after: float | None = None) -> GatewayError:
    """Map an HTTP status to the most specific gateway error type."""
    if status_code in (401, 403):
        return AuthenticationError(message, status_code=status_code)
    if status_code == 429:
        return RateLimitError(message, status_code=status_code, retry_after=retry_after)
    if 400 <= status_code < 500:
        return ClientError(message, status_code=status_code)
    if status_code >= 500:
        return ServerError(message, status_code=status_code)
    return ProtocolError(message, status_code=status_code)
