"""Lever public postings API (no API key required)."""

from __future__ import annotations

from typing import Any

import httpx

from ...domain.models import JobListing
from .base import JobQuery, JobSource, http_get_json, strip_html

_POSTINGS_URL = "https://api.lever.co/v0/postings/{company}?mode=json"


class LeverSource(JobSource):
    id = "lever"
    name = "Lever postings"

    def __init__(self, companies: list[str]) -> None:
        self.companies = [company for company in companies if company.strip()]

    async def search(self, query: JobQuery, *, client: httpx.AsyncClient) -> list[JobListing]:
        listings: list[JobListing] = []
        for company in self.companies:
            if len(listings) >= query.limit:
                break
            response = await http_get_json(client, _POSTINGS_URL.format(company=company))
            for item in response.json() or []:
                listing = _to_listing(item)
                if _matches(listing, query):
                    listings.append(listing)
                if len(listings) >= query.limit:
                    break
        return listings[: query.limit]


def _to_listing(item: dict[str, Any]) -> JobListing:
    categories = item.get("categories") or {}
    all_locations = categories.get("allLocations") or []
    location = str(item.get("location") or "") or ", ".join(str(loc) for loc in all_locations)
    description_html = (
        item.get("descriptionPlain")
        or item.get("description")
        or item.get("text")
        or item.get("additionalPlain")
        or ""
    )
    description = strip_html(str(description_html))
    headline = str(item.get("headline") or item.get("title") or "").strip()
    if not headline and description:
        first_line = description.splitlines()[0].strip()
        headline = first_line[:120]
    url = str(item.get("hostedUrl") or item.get("applyUrl") or "")
    return JobListing(
        external_id=str(item.get("id") or ""),
        source="lever",
        title=headline,
        company=str(item.get("company") or company_from_url(item, url)),
        location=location.strip(),
        description=description,
        url=url,
        salary=None,
        employment_type=categories.get("commitment") or None,
        posted_at=None,
        raw=item,
    )


def company_from_url(item: dict[str, Any], url: str) -> str:
    category_location = (item.get("categories") or {}).get("team") or ""
    return category_location or (url.split("/")[3] if len(url.split("/")) > 3 else "")


def _matches(listing: JobListing, query: JobQuery) -> bool:
    if query.location and query.location.lower() not in listing.location.lower():
        return False
    if not query.query:
        return True
    haystack = f"{listing.title} {listing.company} {listing.description}".lower()
    return query.query.lower() in haystack
