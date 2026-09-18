"""USAJobs API adapter (requires a free API key; optional source)."""

from __future__ import annotations

import httpx

from ...domain.models import JobListing
from .base import JobQuery, JobSource, http_get_json

_BASE_URL = "https://data.usajobs.gov/api/search"


class USAJobsSource(JobSource):
    id = "usajobs"
    name = "USAJobs"

    def __init__(self, api_key: str, email: str) -> None:
        self.api_key = api_key
        self.email = email

    async def search(self, query: JobQuery, *, client: httpx.AsyncClient) -> list[JobListing]:
        if not self.api_key:
            return []
        params: dict[str, str | int | None] = {
            "ResultsPerPage": min(query.limit, 100),
            "RemoteIndicator": str(query.remote_only).lower(),
        }
        if query.query:
            params["Keyword"] = query.query
        if query.location:
            params["LocationName"] = query.location
        headers = {
            "Host": "data.usajobs.gov",
            "User-Agent": self.email,
            "Authorization-Key": self.api_key,
        }
        response = await http_get_json(client, _BASE_URL, params=params, headers=headers)
        payload = response.json()
        listings: list[JobListing] = []
        result = payload.get("SearchResult") or {}
        for item in result.get("SearchResultItems") or []:
            descriptor = item.get("MatchedObjectDescriptor") or {}
            location_display = descriptor.get("PositionLocationDisplay") or ""
            salary_parts = [
                descriptor.get("LowMaximumRange"),
                descriptor.get("HighMaximumRange"),
                descriptor.get("RateIntervalCode"),
            ]
            salary = " - ".join(str(part) for part in salary_parts if part) or None
            listings.append(
                JobListing(
                    external_id=str(
                        descriptor.get("PositionID") or item.get("MatchedObjectId") or ""
                    ),
                    source="usajobs",
                    title=str(descriptor.get("PositionTitle") or "").strip(),
                    company=str(descriptor.get("OrganizationName") or "").strip(),
                    location=str(location_display).strip(),
                    description=str(descriptor.get("QualificationSummary") or "").strip(),
                    url=str(descriptor.get("PositionURI") or ""),
                    salary=salary,
                    employment_type=None,
                    posted_at=str(descriptor.get("PositionStartDate") or "") or None,
                    raw=descriptor,
                )
            )
            if len(listings) >= query.limit:
                break
        return listings
