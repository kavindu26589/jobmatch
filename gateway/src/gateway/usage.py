"""Token/cost usage tracking.

Every request that returns a ``Usage`` block is recorded on the gateway's
:class:`UsageLedger`. Default per-1M pricing leans on OpenCode Zen's published
rates; model lookups fall back from exact id, to prefix, to :data:`_DEFAULT`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cached_input_tokens


@dataclass(frozen=True)
class CostTable:
    input_per_1m: float
    output_per_1m: float
    cached_read_per_1m: float = 0.0

    def compute(self, usage: Usage) -> float:
        return (
            usage.input_tokens / 1_000_000 * self.input_per_1m
            + usage.output_tokens / 1_000_000 * self.output_per_1m
            + usage.cached_input_tokens / 1_000_000 * self.cached_read_per_1m
        )


@dataclass(frozen=True)
class UsageRecord:
    provider_id: str
    model_id: str
    usage: Usage
    cost_usd: float
    started_at: float
    latency_ms: int
    request_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "cached_input_tokens": self.usage.cached_input_tokens,
            "total_tokens": self.usage.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": self.latency_ms,
            "request_id": self.request_id,
            "started_at": datetime.fromtimestamp(self.started_at, tz=UTC).isoformat(),
        }


# Documented OpenCode Zen rates. Missing models fall back to prefix matching.
_DEFAULT = CostTable(input_per_1m=0.50, output_per_1m=1.50, cached_read_per_1m=0.10)

PRICING: dict[str, CostTable] = {
    # Zen GPT-5 family
    "gpt-6-astra": CostTable(10.00, 50.00, 1.00),
    "gpt-5.6-sol": CostTable(2.00, 10.00, 0.20),
    "gpt-5.6-terra": CostTable(2.00, 12.00, 0.20),
    "gpt-5.6-luna": CostTable(0.20, 1.20, 0.02),
    "gpt-5.5": CostTable(5.00, 30.00, 0.50),
    "gpt-5.4": CostTable(2.50, 15.00, 0.25),
    "gpt-5.4-mini": CostTable(0.75, 4.50, 0.075),
    "gpt-5.4-nano": CostTable(0.20, 1.25, 0.02),
    "gpt-5.3-codex": CostTable(1.75, 14.00, 0.175),
    "gpt-5.2": CostTable(1.75, 14.00, 0.175),
    "gpt-5.1": CostTable(1.07, 8.50, 0.107),
    "gpt-5": CostTable(1.07, 8.50, 0.107),
    "gpt-5-nano": CostTable(0.05, 0.40, 0.005),
    # Zen Claude family
    "claude-sonnet-5": CostTable(2.00, 10.00, 0.20),
    "claude-sonnet-4.6": CostTable(3.00, 15.00, 0.30),
    "claude-sonnet-4.5": CostTable(3.00, 15.00, 0.30),
    "claude-haiku-4.5": CostTable(1.00, 5.00, 0.10),
    "claude-opus-5": CostTable(5.00, 25.00, 0.50),
    "claude-opus-4.8": CostTable(5.00, 25.00, 0.50),
    "claude-fable-5.1": CostTable(10.00, 50.00, 0.25),
    # Zen Gemini family
    "gemini-3.7-flash": CostTable(1.50, 7.50, 0.15),
    "gemini-3.6-flash": CostTable(1.50, 7.50, 0.15),
    "gemini-3.5-flash": CostTable(1.50, 9.00, 0.15),
    "gemini-3.5-flash-lite": CostTable(0.30, 2.50, 0.03),
    "gemini-3.1-pro": CostTable(2.00, 12.00, 0.20),
    # Zen DeepSeek / GLM / Kimi
    "deepseek-v4-pro": CostTable(1.74, 3.48, 0.145),
    "deepseek-v4-flash": CostTable(0.14, 0.28, 0.028),
    "glm-5.3-flash": CostTable(0.15, 0.50, 0.03),
    "glm-5.3": CostTable(1.40, 4.40, 0.26),
    "kimi-k2.5": CostTable(0.60, 3.00, 0.10),
    "kimi-k2.6": CostTable(0.95, 4.00, 0.16),
    # Direct providers
    "gpt-5.4-mini-2025-07-24": CostTable(0.75, 4.50, 0.075),
    "gpt-5.4-nano-2025-07-08": CostTable(0.20, 1.25, 0.02),
}

_PREFIX_ORDER = [
    "claude-fable",
    "claude-opus",
    "claude-sonnet",
    "claude-haiku",
    "gpt-6",
    "gpt-5",
    "gpt-4",
    "gemini-3",
    "gemini-2",
    "deepseek",
    "glm-5",
    "kimi-k",
    "grok",
    "llama",
    "mistral",
    "qwen",
]


def pricing_for(model_id: str) -> CostTable:
    """Best-effort cost table for a model id."""
    lowered = model_id.lower().strip("/")
    if lowered in PRICING:
        return PRICING[lowered]
    for prefix in sorted(_PREFIX_ORDER, key=len, reverse=True):
        for known in PRICING:
            if known.startswith(prefix) and lowered.startswith(prefix):
                return PRICING[known]
    return _DEFAULT


class SpendBudgetExceededError(Exception):
    """Internal marker used when the gateway budget guard trips."""


class UsageLedger:
    """Thread-safe collector of usage records, usable as a budget source."""

    def __init__(self, budget_usd: float | None = None) -> None:
        self._records: list[UsageRecord] = []
        self._lock = threading.Lock()
        self.budget_usd = budget_usd

    def record(self, record: UsageRecord) -> None:
        with self._lock:
            self._records.append(record)

    def snapshot(self) -> list[UsageRecord]:
        with self._lock:
            return list(self._records)

    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.snapshot())

    def ensure_within_budget(self) -> None:
        """Raise if cumulative spend meets or exceeds the configured budget."""
        if self.budget_usd is not None and self.total_cost() >= self.budget_usd:
            from .errors import BudgetExceeded

            raise BudgetExceeded(self.budget_usd, self.total_cost())

    def write_jsonl(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for record in self.snapshot():
                handle.write(json_dump(record.as_dict()) + "\n")
        return target


def json_dump(value: dict[str, object]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)
