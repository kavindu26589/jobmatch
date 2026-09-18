"""Greenhouse public job boards (no API key required)."""

from __future__ import annotations

from typing import Any

import httpx

from ...domain.models import JobListing
from .base import JobQuery, JobSource, http_get_json, strip_html

_BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


class GreenhouseSource(JobSource):
    id = "greenhouse"
    name = "Greenhouse job boards"

    def __init__(self, boards: list[str]) -> None:
        self.boards = [board for board in boards if board.strip()]

    async def search(self, query: JobQuery, *, client: httpx.AsyncClient) -> list[JobListing]:
        listings: list[JobListing] = []
        for board in self.boards:
            if len(listings) >= query.limit:
                break
            response = await http_get_json(
                client, _BOARD_URL.format(board=board), params={"content": "true"}
            )
            payload = response.json()
            for item in payload.get("jobs") or []:
                listing = _to_listing(item, board)
                if _matches(listing, query):
                    listings.append(listing)
                if len(listings) >= query.limit:
                    break
        return listings[: query.limit]


def _to_listing(item: dict[str, Any], board: str) -> JobListing:
    location = (item.get("location") or {}).get("name") or ""
    departments = " ".join(
        department.get("name", "") for department in (item.get("departments") or [])
    )
    content = strip_html(str(item.get("content") or ""))
    description = f"{departments}\n{content}".strip()
    return JobListing(
        external_id=str(item.get("id") or ""),
        source="greenhouse",
        title=str(item.get("title") or "").strip(),
        company=board,
        location=str(location).strip(),
        description=description,
        url=str(item.get("absolute_url") or "") or None,
        employment_type=None,
        posted_at=str(item.get("updated_at") or "") or None,
        raw=item,
    ).model_copy(update={"url": str(item.get("absolute_url") or "")})


def _matches(listing: JobListing, query: JobQuery) -> bool:
    if query.location and query.location.lower() not in listing.location.lower():
        return False
    if not query.query:
        return True
    haystack = f"{listing.title} {listing.description}".lower()
    return query.query.lower() in haystack
