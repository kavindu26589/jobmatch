"""High-level LLM gateway.

Wraps protocol clients with retries, backoff, rate limiting, circuit
breaking, budget enforcement, cost accounting, and structured output.

The gateway is deliberately engine-agnostic (no LangChain/LangGraph here): it
is an async HTTP client over OpenAI/Anthropic-compatible endpoints, which is
exactly what makes it usable from any other system.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
import uuid
from collections.abc import AsyncIterator, Coroutine, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import TypeAdapter

from .config import ProviderConfig
from .errors import (
    GatewayError,
    MaxRetriesExceeded,
    NetworkError,
    ProtocolError,
    is_retryable,
)
from .protocols import (
    EMIT_TOOL_NAME,
    ChatRequest,
    ChatResult,
    Message,
    ProtocolClient,
    ToolSpec,
    build_protocol_client,
    json_tool,
)
from .providers import ProviderRegistry
from .security import redact
from .usage import Usage, UsageLedger, UsageRecord, pricing_for

logger = logging.getLogger("opencode_gateway")

T = TypeVar("T")


class CircuitOpenError(NetworkError):
    """The circuit is open; fail fast until the reset window elapses."""


class AsyncRateLimiter:
    """Token-bucket limiter (async). ``capacity`` is burst size,
    ``refill_per_second`` recharges it."""

    def __init__(self, capacity: float, refill_per_second: float) -> None:
        self._capacity = max(capacity, 1.0)
        self._refill = max(refill_per_second, 0.0)
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._refill)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                wait = (
                    (tokens - self._tokens) / self._refill if self._refill > 0 else self._capacity
                )
            await asyncio.sleep(wait)


class CircuitBreaker:
    """Trips after ``failure_threshold`` consecutive failures, resets after ``reset_after`` s."""

    def __init__(self, failure_threshold: int = 5, reset_after: float = 30.0) -> None:
        self.failure_threshold = max(failure_threshold, 1)
        self.reset_after = max(reset_after, 1.0)
        self._failures = 0
        self._opened_at: float | None = None

    def before(self) -> None:
        if self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.reset_after:
                self._opened_at = None
                self._failures = 0
            else:
                raise CircuitOpenError("circuit breaker open; provider considered unhealthy")

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()


@dataclass
class CallOptions:
    temperature: float | None = None
    max_tokens: int | None = None
    stop: list[str] = field(default_factory=list)
    max_attempts: int | None = None
    record_usage: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def _default_env() -> dict[str, str]:
    return dict(os.environ)


def _run(coro: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("already inside an event loop; use the async methods instead")


class LLMGateway:
    """Retrying, budgeted, rate-limited chat client over a provider registry."""

    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        env: Mapping[str, str] | None = None,
        default_max_attempts: int = 3,
        rate_limiter: AsyncRateLimiter | None = None,
        ledger: UsageLedger | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self.registry = registry
        self.env = dict(env) if env is not None else _default_env()
        self.default_max_attempts = default_max_attempts
        self.rate_limiter = rate_limiter or AsyncRateLimiter(
            capacity=10_000, refill_per_second=10_000
        )
        self.ledger = ledger or UsageLedger()
        self.breaker = breaker or CircuitBreaker()
        self._clients: dict[str, ProtocolClient] = {}

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _client_for(provider: ProviderConfig) -> ProtocolClient:
        return build_protocol_client(provider.protocol)

    def _record_usage(
        self,
        provider_id: str,
        model_id: str,
        usage: Usage,
        *,
        started_at: float,
        request_id: str,
        enabled: bool,
    ) -> None:
        if not enabled:
            return
        cost = pricing_for(model_id).compute(usage)
        record = UsageRecord(
            provider_id=provider_id,
            model_id=model_id,
            usage=usage,
            cost_usd=cost,
            started_at=started_at,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            request_id=request_id,
        )
        self.ledger.record(record)
        logger.info(
            "llm %s/%s tokens=%d cost=%.5f latency=%dms",
            provider_id,
            model_id,
            usage.total_tokens,
            cost,
            record.latency_ms,
        )

    async def _backoff(self, attempt: int, error: GatewayError) -> None:
        base = 0.5 * (2**attempt)
        jitter = random.uniform(0, base * 0.3)
        retry_after = getattr(error, "retry_after", None)
        delay = base + jitter
        if retry_after is not None:
            delay = min(max(delay, min(float(retry_after), 60.0)), 60.0)
        delay = min(delay, 60.0)
        logger.warning(
            "llm retry attempt=%d in %.2fs reason=%s", attempt + 1, delay, type(error).__name__
        )
        await asyncio.sleep(delay)

    # -- public API ---------------------------------------------------------

    async def chat(
        self,
        provider_id: str,
        model_id: str,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        tool_choice: str = "auto",
        force_tool: str | None = None,
        json_mode: bool = False,
        options: CallOptions | None = None,
    ) -> ChatResult:
        opts = options or CallOptions()
        provider = self.registry.get(provider_id)
        client = self._clients.setdefault(provider_id, self._client_for(provider))
        request = ChatRequest(
            model=model_id,
            messages=messages,
            tools=tools or [],
            tool_choice=tool_choice,  # type: ignore[arg-type]
            force_tool=force_tool,
            json_mode=json_mode,
            temperature=opts.temperature,
            max_tokens=opts.max_tokens,
            stop=opts.stop,
            extra=opts.extra,
        )
        max_attempts = opts.max_attempts or provider.max_retries or self.default_max_attempts
        max_attempts = max(1, max_attempts)
        request_id = uuid.uuid4().hex[:12]
        errors: list[GatewayError] = []
        started_at = time.monotonic()

        for attempt in range(max_attempts):
            self.breaker.before()
            self.ledger.ensure_within_budget()
            await self.rate_limiter.acquire(1.0)
            try:
                result = await client.chat(provider, request, env=self.env)
            except CircuitOpenError:
                self.breaker.record_failure()
                raise
            except GatewayError as exc:
                errors.append(exc)
                self.breaker.record_failure()
                if is_retryable(exc) and attempt < max_attempts - 1:
                    await self._backoff(attempt, exc)
                    continue
                if is_retryable(exc):
                    raise MaxRetriesExceeded(
                        f"chat request {request_id!r} failed", attempts=attempt + 1, errors=errors
                    ) from exc
                raise
            self.breaker.record_success()
            self._record_usage(
                provider_id,
                model_id,
                result.usage,
                started_at=started_at,
                request_id=request_id,
                enabled=opts.record_usage,
            )
            return result
        raise MaxRetriesExceeded(
            f"chat request {request_id!r} failed", attempts=max_attempts, errors=errors
        )

    async def chat_stream(
        self,
        provider_id: str,
        model_id: str,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        provider = self.registry.get(provider_id)
        client = self._clients.setdefault(provider_id, self._client_for(provider))
        request = ChatRequest(
            model=model_id,
            messages=messages,
            tools=tools or [],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.breaker.before()
        await self.rate_limiter.acquire(1.0)
        async for delta in client.chat_stream(provider, request, env=self.env):
            yield delta

    async def complete(
        self,
        provider_id: str,
        model_id: str,
        prompt: str,
        *,
        system: str | None = None,
        options: CallOptions | None = None,
    ) -> str:
        messages: list[Message] = []
        if system:
            messages.append(Message(role="system", content=system))
        messages.append(Message(role="user", content=prompt))
        result = await self.chat(provider_id, model_id, messages, options=options)
        return result.content

    async def structured(
        self,
        provider_id: str,
        model_id: str,
        *,
        schema: type[T] | TypeAdapter[T],
        system: str | None = None,
        user: str | None = None,
        messages: list[Message] | None = None,
        options: CallOptions | None = None,
    ) -> T:
        """Ask the model to emit an object matching ``schema`` (pydantic).

        Produces strict parsing of the model's ``emit_json`` tool call; falls
        back to JSON embedded in free text.
        """
        adapter = schema if isinstance(schema, TypeAdapter) else TypeAdapter(schema)
        instructional = (
            "You must call the provided emit_json tool with your final answer as valid JSON "
            "matching the tool's JSON schema. Do not emit anything else."
        )
        built: list[Message] = []
        if messages is not None:
            built = list(messages)
            if built and built[0].role == "system":
                built[0] = Message(role="system", content=f"{built[0].content}\n\n{instructional}")
            elif system:
                built.insert(0, Message(role="system", content=f"{system}\n\n{instructional}"))
        else:
            if system:
                built.append(Message(role="system", content=f"{system}\n\n{instructional}"))
            if user:
                built.append(Message(role="user", content=user))
        tool = json_tool(schema=adapter.json_schema())
        result = await self.chat(
            provider_id,
            model_id,
            built,
            tools=[tool],
            force_tool=EMIT_TOOL_NAME,
            options=options,
        )
        return _coerce_structured(result, adapter, instructional)

    def chat_sync(
        self, provider_id: str, model_id: str, messages: list[Message], **kwargs: Any
    ) -> ChatResult:
        return _run(self.chat(provider_id, model_id, messages, **kwargs))

    def complete_sync(self, provider_id: str, model_id: str, prompt: str, **kwargs: Any) -> str:
        return _run(self.complete(provider_id, model_id, prompt, **kwargs))

    def structured_sync(self, provider_id: str, model_id: str, **kwargs: Any) -> Any:
        return _run(self.structured(provider_id, model_id, **kwargs))

    # -- observability ------------------------------------------------------

    def usage_snapshot(self) -> list[UsageRecord]:
        return self.ledger.snapshot()

    def total_cost(self) -> float:
        return self.ledger.total_cost()

    def write_usage(self, path: str) -> Any:
        return self.ledger.write_jsonl(path)


def _find_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first balanced JSON object from arbitrary text."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            char = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : idx + 1]
                    try:
                        return dict(json.loads(candidate))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        start = text.find("{", start + 1)
                        break
        start = text.find("{", start + 1)
    return None


def _coerce_structured(result: ChatResult, adapter: TypeAdapter[T], hint: str) -> T:
    candidates: list[Any] = []
    for call in result.tool_calls:
        if call.name == EMIT_TOOL_NAME:
            candidates.append(call.arguments)
    if result.content.strip():
        parsed = _find_json_object(result.content)
        if parsed is not None:
            candidates.append(parsed)
    for candidate in candidates:
        try:
            return adapter.validate_python(candidate)
        except Exception:
            continue
    proposal = candidates[0] if candidates else result.content[:200]
    raise ProtocolError(f"model output did not match the requested schema: {redact(str(proposal))}")
