"""Job source adapters and their factory."""

from __future__ import annotations

from .base import JobQuery, JobSource, strip_html
from .greenhouse import GreenhouseSource
from .lever import LeverSource
from .remotive import RemotiveSource
from .usajobs import USAJobsSource

SOURCE_IDS = ("remotive", "greenhouse", "lever", "usajobs")


def create_job_sources(
    source_ids: list[str],
    *,
    greenhouse_boards: list[str] | None = None,
    lever_companies: list[str] | None = None,
    usajobs_api_key: str | None = None,
    usajobs_email: str = "",
) -> list[JobSource]:
    """Build source adapters from a list of ids, ignoring unknown ids."""
    adapters: list[JobSource] = []
    for source_id in source_ids:
        if source_id == "remotive":
            adapters.append(RemotiveSource())
        elif source_id == "greenhouse":
            adapters.append(GreenhouseSource(greenhouse_boards or []))
        elif source_id == "lever":
            adapters.append(LeverSource(lever_companies or []))
        elif source_id == "usajobs":
            adapters.append(USAJobsSource(usajobs_api_key or "", usajobs_email or ""))
    return adapters


__all__ = [
    "SOURCE_IDS",
    "GreenhouseSource",
    "JobQuery",
    "JobSource",
    "LeverSource",
    "RemotiveSource",
    "USAJobsSource",
    "create_job_sources",
    "strip_html",
]
