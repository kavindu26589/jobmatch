"""Job source abstraction and shared HTTP plumbing."""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel

from ...domain.models import JobListing

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return re.sub(r"[ \t]+", " ", _HTML_TAG_RE.sub(" ", text or "")).strip()


class JobQuery(BaseModel):
    query: str = ""
    location: str = ""
    remote_only: bool = False
    limit: int = 25


class JobSource(ABC):
    """A single provider of job postings fetched over the internet."""

    id: str = "base"
    name: str = "Base"

    @abstractmethod
    async def search(self, query: JobQuery, *, client: httpx.AsyncClient) -> list[JobListing]:
        """Return listings matching ``query``. Implementations may fetch and
        filter locally; they must never raise unexpected exceptions (unmarshal
        errors are reported by the caller)."""


async def http_get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str | int | None] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 2,
) -> httpx.Response:
    """GET ``url`` with bounded retries; raises after exhausted retries."""
    last_message = "request failed"
    last_status = 0
    request = httpx.Request("GET", url)
    for attempt in range(retries + 1):
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.TransportError as exc:
            last_message = str(exc)
            await _sleep(attempt)
            continue
        if response.status_code < 400:
            return response
        last_status = response.status_code
        last_message = f"HTTP {response.status_code} from {url}"
        await _sleep(attempt)
    raise httpx.HTTPStatusError(
        last_message,
        request=request,
        response=httpx.Response(last_status, text=last_message),
    )


async def _sleep(attempt: int) -> None:
    if attempt < 3:
        await asyncio.sleep(0.25 * (attempt + 1))
