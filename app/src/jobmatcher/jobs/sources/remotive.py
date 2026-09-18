"""Remotive: no-key remote job board API."""

from __future__ import annotations

import re
from typing import Any

import httpx

from ...domain.models import JobListing
from .base import JobQuery, JobSource, http_get_json, strip_html

_BASE_URL = "https://remotive.com/api/remote-jobs"
_TOKEN_RE = re.compile(r"[a-z0-9+#]+")


class RemotiveSource(JobSource):
    id = "remotive"
    name = "Remotive (remote jobs)"

    async def search(self, query: JobQuery, *, client: httpx.AsyncClient) -> list[JobListing]:
        params: dict[str, str | int | None] = {"limit": min(query.limit, 100)}
        if query.query:
            params["search"] = query.query
        response = await http_get_json(client, _BASE_URL, params=params)
        payload = response.json()
        listings: list[JobListing] = []
        for item in payload.get("jobs") or []:
            listing = _to_listing(item)
            if _matches(listing, query):
                listings.append(listing)
            if len(listings) >= query.limit:
                break
        return listings


def _to_listing(item: dict[str, Any]) -> JobListing:
    description = strip_html(str(item.get("description") or ""))
    return JobListing(
        external_id=str(item.get("id") or ""),
        source="remotive",
        title=str(item.get("title") or "").strip(),
        company=str(item.get("company_name") or "").strip(),
        location=str(item.get("candidate_required_location") or "").strip(),
        description=description,
        url=str(item.get("url") or ""),
        salary=str(item.get("salary") or "") or None,
        employment_type=str(item.get("job_type") or "") or None,
        posted_at=str(item.get("publication_date") or "") or None,
        raw=item,
    )


def _matches(listing: JobListing, query: JobQuery) -> bool:
    if query.location and query.location.lower() not in listing.location.lower():
        return False
    if not query.query:
        return True
    haystack = f"{listing.title} {listing.company} {listing.description}".lower()
    # Match on every significant term rather than the raw phrase: remotive's
    # backend treats the query as one literal string, so "python developer"
    # returns nothing even when many listings mention both words.
    tokens = _TOKEN_RE.findall(query.query.lower())
    return all(token in haystack for token in tokens) if tokens else True
