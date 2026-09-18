"""Usage accounting, cost estimation, ledger, budget enforcement."""

from __future__ import annotations

import pytest

from gateway.errors import BudgetExceeded
from gateway.usage import CostTable, Usage, UsageLedger, UsageRecord, pricing_for


def test_pricing_lookup() -> None:
    assert pricing_for("gpt-5.4-mini").input_per_1m == 0.75
    assert pricing_for("gpt-5.4-mini-2025-07-24").input_per_1m == 0.75
    assert pricing_for("deepseek-v4-flash").output_per_1m == 0.28
    fallback = pricing_for("unknown-model-x")
    assert fallback.input_per_1m > 0


def test_cost_computation() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=500_000, cached_input_tokens=1_000_000)
    cost = CostTable(1.0, 2.0, 0.5).compute(usage)
    assert cost == pytest.approx(1.0 + 1.0 + 0.5)


def test_ledger_records_and_budget() -> None:
    ledger = UsageLedger(budget_usd=1.0)
    record = UsageRecord(
        provider_id="zen",
        model_id="gpt-5.4-mini",
        usage=Usage(input_tokens=100, output_tokens=100),
        cost_usd=0.6,
        started_at=0.0,
        latency_ms=10,
        request_id="r1",
    )
    ledger.record(record)
    assert ledger.total_cost() == pytest.approx(0.6)
    ledger.ensure_within_budget()  # 0.6 < 1.0

    ledger.record(record)
    with pytest.raises(BudgetExceeded):
        ledger.ensure_within_budget()


def test_jsonl_export(tmp_path) -> None:
    ledger = UsageLedger()
    ledger.record(
        UsageRecord(
            "zen", "m", Usage(1, 2), 0.001, started_at=1_700_000_000.0, latency_ms=5, request_id="x"
        )
    )
    out = ledger.write_jsonl(tmp_path / "u.jsonl")
    assert out.exists()
    assert '"input_tokens": 1' in out.read_text(encoding="utf-8")


def test_usage_total_tokens() -> None:
    assert Usage(1, 2, 3).total_tokens == 6
