"""Optional MLflow-backed correctness telemetry for the occurrence-binding engine.

Correctness here means **occurrence binding**: the Nth *approved* change must
bind to exactly the occurrence that ``preview_binary`` located (same ``page``/
``box``, same deterministic ``_plan`` traversal). No human labels, no LLM gold
set �?" the ground truth is structural, reproducible, and shared by preview and
apply.

Contract (must match pdfpatch ``patch_binary``)::

    from .metrics import maybe_apply_metrics
    maybe_apply_metrics(data, changes, kind, approve)

Rules:
* MLflow is **optional and lazy**. If ``mlflow`` cannot be imported, events
  degrade to an append-only JSONL file under ``eval_dir``; if that also fails,
  the event is dropped silently. This module *never* raises into a patch edit.
* The HTTP server image stays lean �?" no MLflow inside the image. Telemetry
  imports ``mlflow`` only when it is installed in the dev/eval venv.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("jobmatcher.metrics")

_MLFLOW_URI_KEY = "MLFLOW_TRACKING_URI"
_EVAL_DIR_KEY = "JOBMATCHER_EVAL_DIR"
_EXPERIMENT_DEFAULT = "jobmatcher-patch-binding"
_DEFAULT_EVAL_DIR = Path(".eval") / "metrics-events"

_mlflow_module: Any | None = None
_mlflow_import_attempted = False


def _eval_dir_from_env() -> Path:
    raw = os.environ.get(_EVAL_DIR_KEY)
    if raw:
        return Path(raw)
    return _DEFAULT_EVAL_DIR


@dataclass
class EvalSettings:
    """Runtime-selected eval/telemetry knobs (all env-overridable)."""

    eval_dir: Path = field(default_factory=_eval_dir_from_env)
    experiment: str = field(default_factory=lambda: _EXPERIMENT_DEFAULT)
    tracking_uri: str | None = None


_settings = EvalSettings()


def _import_mlflow() -> Any | None:
    """Lazy, cached import; returns ``None`` when MLflow is unavailable."""
    global _mlflow_module, _mlflow_import_attempted
    if _mlflow_import_attempted:
        return _mlflow_module
    _mlflow_import_attempted = True
    try:
        import mlflow  # type: ignore[import-not-found]

        _mlflow_module = mlflow
    except Exception:
        _mlflow_module = None
    return _mlflow_module


def configure(
    *,
    eval_dir: str | os.PathLike[str] | None = None,
    experiment: str | None = None,
    tracking_uri: str | None = None,
) -> EvalSettings:
    """Override eval defaults (used by the eval harness / server startup)."""
    if eval_dir is not None:
        _settings.eval_dir = Path(eval_dir)
    if experiment:
        _settings.experiment = experiment
    if tracking_uri:
        _settings.tracking_uri = tracking_uri
    return _settings


def _jsonl_path() -> Path:
    return _settings.eval_dir / "events.jsonl"


def _append_jsonl(event: dict[str, Any]) -> None:
    try:
        path = _jsonl_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=str, sort_keys=True))
            handle.write("\n")
    except Exception:
        logger.warning("metrics: could not append JSONL event", exc_info=True)


def _emit(metrics: dict[str, float], **params: Any) -> None:
    """Ship one event to MLflow (if available) else JSONL. Never raises."""
    event: dict[str, Any] = {
        "experiment": _settings.experiment,
        "params": {key: value for key, value in params.items()},
        "metrics": {key: round(float(value), 6) for key, value in metrics.items()},
        "tracking_uri": _settings.tracking_uri,
        "ts": time.time(),
    }
    mlflow = _import_mlflow()
    if mlflow is not None:
        try:
            mlflow.set_experiment(event["experiment"])
            with mlflow.start_run() as _run:
                for key, value in event["params"].items():
                    if value is not None:
                        mlflow.log_param(key, value)
                for key, value in event["metrics"].items():
                    mlflow.log_metric(key, value)
            return
        except Exception:
            logger.warning("metrics: mlflow emit failed; degrading to JSONL", exc_info=True)
    _append_jsonl(event)


def maybe_apply_metrics(
    data: bytes,
    changes: list[Any],
    kind: Literal["pdf", "docx"],
    approve: set[int] | None = None,
) -> None:
    """Contract entry called by ``pdfpatch.patch_binary`` (never raises).

    Derives binding correctness from the *same* ``_plan(data, changes, kind)``
    traversal that ``preview_binary``/``apply_binary`` share, so the Nth
    approved occurrence binds to exactly the page/box previewed.
    """
    if not changes:
        _emit({"binding_precision": 1.0, "binding_recall": 1.0}, stage="apply", kind=kind)
        return
    from .pdfpatch import _plan

    try:
        targets, placeable = _plan(data, changes, kind)
    except Exception:
        logger.warning("metrics: _plan failed; dropping event", exc_info=True)
        return

    occurrence_to_target = {
        getattr(target, "occurrence", index): target for index, target in enumerate(targets)
    }
    total = len(changes)
    approve = approve if approve is not None else set(range(total))
    approved_placeable = sum(
        1 for index in approve if getattr(occurrence_to_target.get(index), "placeable", False)
    )
    placeable_rate = placeable / total if total else 0.0
    binding_precision = approved_placeable / len(approve) if approve else 0.0
    binding_recall = approved_placeable / placeable if placeable else (1.0 if not approve else 0.0)
    _emit(
        {
            "binding_precision": binding_precision,
            "binding_recall": binding_recall,
            "placeable_rate": placeable_rate,
            "approved_placeable": float(approved_placeable),
            "placeable": float(placeable),
            "total": float(total),
        },
        stage="apply",
        kind=kind,
        experiment=_settings.experiment,
        approve_size=float(len(approve)),
        data_kb=round(len(data) / 1024, 2),
    )


def record_preview(
    *,
    data: bytes,
    original_text: str,
    edited_text: str,
    kind: str,
    result: Any,
) -> None:
    """Event per preview call: how many located changes are placeable."""
    placeable = 0
    total = 0
    for target in getattr(result, "targets", []) or []:
        placeable += int(getattr(target, "placeable", False))
        total += 1
    _emit(
        {
            "placeable_rate": (placeable / total) if total else 0.0,
            "placeable": float(placeable),
            "total": float(total),
        },
        stage="preview",
        kind=kind,
        original_chars=len(original_text),
        edited_chars=len(edited_text),
        data_kb=round(len(data) / 1024, 2),
    )


def record_apply(
    *,
    data: bytes,
    original_text: str,
    edited_text: str,
    kind: str,
    approve: set[int] | None,
    result: Any,
) -> None:
    """Event per apply call: applied/total and binding correctness."""
    applied = int(getattr(result, "applied", 0))
    total = int(getattr(result, "total", 0))
    approve_size = len(approve or set())
    binding_exact = 1.0 if (approve_size and applied == approve_size) else 0.0
    _emit(
        {
            "binding_exact": binding_exact,
            "binding_recall": (applied / approve_size) if approve_size else 0.0,
            "apply_rate": (applied / total) if total else 0.0,
        },
        stage="apply",
        kind=kind,
        approve_size=float(approve_size),
        original_chars=len(original_text),
        edited_chars=len(edited_text),
        data_kb=round(len(data) / 1024, 2),
    )
