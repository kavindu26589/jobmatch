"""Concurrent, deduplicated job search across sources."""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..domain.models import JobListing
from .sources import JobQuery, JobSource

logger = logging.getLogger("jobmatcher.jobs")


class JobSearcher:
    """Runs a :class:`JobQuery` against every configured source concurrently."""

    def __init__(self, sources: list[JobSource]) -> None:
        self.sources = sources
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> JobSearcher:
        self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search(self, query: JobQuery) -> tuple[list[JobListing], list[str]]:
        if not self.sources:
            return [], ["no job sources configured"]
        client = self._client or httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        per_source = max(1, query.limit // len(self.sources))

        async def run(source: JobSource) -> list[JobListing]:
            limited = query.model_copy(update={"limit": per_source})
            return await source.search(limited, client=client)

        results = await asyncio.gather(
            *(run(source) for source in self.sources), return_exceptions=True
        )
        listings: list[JobListing] = []
        warnings: list[str] = []
        for source, outcome in zip(self.sources, results, strict=False):
            if isinstance(outcome, BaseException):
                logger.warning("job source %s failed: %s", source.id, outcome)
                warnings.append(f"source '{source.id}' failed: {outcome}")
                continue
            listings.extend(outcome)
        deduped = self._dedupe(listings)
        return deduped[: query.limit], warnings

    @staticmethod
    def _dedupe(listings: list[JobListing]) -> list[JobListing]:
        seen_keys: set[str] = set()
        seen_normalized: set[str] = set()
        unique: list[JobListing] = []
        for listing in listings:
            if listing.dedupe_key() in seen_keys:
                continue
            normalized = listing.normalized_key()
            if normalized in seen_normalized:
                continue
            seen_keys.add(listing.dedupe_key())
            seen_normalized.add(normalized)
            unique.append(listing)
        return unique
