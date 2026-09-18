"""Tests for job-source adapters using mocked HTTP endpoints."""

from __future__ import annotations

import httpx
import respx

from jobmatcher.jobs.sources.base import JobQuery, strip_html
from jobmatcher.jobs.sources.greenhouse import GreenhouseSource
from jobmatcher.jobs.sources.lever import LeverSource
from jobmatcher.jobs.sources.remotive import RemotiveSource


def test_strip_html_removes_tags_and_collapses_space():
    assert strip_html("<p>Hello <b>world</b></p><br/>") == "Hello world"


@respx.mock
async def test_remotive_parses_and_filters():
    respx.get("https://remotive.com/api/remote-jobs").respond(
        json={
            "jobs": [
                {
                    "id": "1",
                    "title": "Backend Engineer",
                    "company_name": "Acme",
                    "candidate_required_location": "Remote",
                    "description": "<p>Python backend work.</p>",
                    "url": "https://remotive.com/jobs/1",
                    "salary": "100k",
                    "job_type": "full_time",
                    "publication_date": "2026-01-01",
                },
                {
                    "id": "2",
                    "title": "Barista",
                    "company_name": "Cafe",
                    "candidate_required_location": "New York",
                    "description": "Front of house.",
                    "url": "https://remotive.com/jobs/2",
                },
            ]
        }
    )
    async with httpx.AsyncClient() as client:
        listings = await RemotiveSource().search(JobQuery(query="python", limit=10), client=client)
    assert len(listings) == 1
    assert listings[0].source == "remotive"
    assert listings[0].company == "Acme"
    assert listings[0].title == "Backend Engineer"
    assert listings[0].salary == "100k"


@respx.mock
async def test_remotive_matches_all_query_terms_not_literal_phrase():
    respx.get("https://remotive.com/api/remote-jobs").respond(
        json={
            "jobs": [
                {
                    "id": "1",
                    "title": "Python Developer",
                    "company_name": "Acme",
                    "candidate_required_location": "Remote",
                    "description": "<p>Build backend services in Python.</p>",
                    "url": "https://remotive.com/jobs/1",
                    "salary": "100k",
                    "job_type": "full_time",
                    "publication_date": "2026-01-01",
                },
                {
                    "id": "2",
                    "title": "Barista",
                    "company_name": "Cafe",
                    "candidate_required_location": "Remote",
                    "description": "Front of house.",
                    "url": "https://remotive.com/jobs/2",
                },
            ]
        }
    )
    async with httpx.AsyncClient() as client:
        listings = await RemotiveSource().search(
            JobQuery(query="python developer", limit=10), client=client
        )
    assert [listing.title for listing in listings] == ["Python Developer"]


@respx.mock
async def test_greenhouse_parses_board_jobs():
    respx.get(url__startswith="https://boards-api.greenhouse.io/v1/boards").respond(
        json={
            "jobs": [
                {
                    "id": "101",
                    "title": "Data Engineer",
                    "location": {"name": "Remote"},
                    "departments": [{"name": "Engineering"}],
                    "content": "<p>ETL in Python.</p>",
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/101",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ]
        }
    )
    async with httpx.AsyncClient() as client:
        listings = await GreenhouseSource(["acme"]).search(
            JobQuery(query="engin", limit=10), client=client
        )
    assert len(listings) == 1
    listing = listings[0]
    assert listing.company == "acme"
    assert listing.location == "Remote"
    assert listing.description == "Engineering\nETL in Python."
    assert listing.url == "https://boards.greenhouse.io/acme/jobs/101"


@respx.mock
async def test_greenhouse_filters_by_location():
    respx.get(url__startswith="https://boards-api.greenhouse.io/v1/boards").respond(
        json={
            "jobs": [
                {
                    "id": "1",
                    "title": "Engineer",
                    "location": {"name": "Berlin"},
                    "content": "text",
                    "absolute_url": "https://x/jobs/1",
                },
                {
                    "id": "2",
                    "title": "Engineer",
                    "location": {"name": "Remote"},
                    "content": "text",
                    "absolute_url": "https://x/jobs/2",
                },
            ]
        }
    )
    async with httpx.AsyncClient() as client:
        listings = await GreenhouseSource(["acme"]).search(
            JobQuery(query="", location="berlin", limit=10), client=client
        )
    assert [item.location for item in listings] == ["Berlin"]


@respx.mock
async def test_lever_parses_locations_and_headline():
    respx.get("https://api.lever.co/v0/postings/shopify?mode=json").respond(
        json=[
            {
                "id": "abc",
                "headline": "Backend Engineer",
                "location": "Berlin",
                "categories": {"allLocations": ["Berlin", "Remote"], "commitment": "full-time"},
                "descriptionPlain": "Work on Python APIs with PostgreSQL.",
                "hostedUrl": "https://jobs.lever.co/shopify/abc",
                "company": "Shopify",
            }
        ]
    )
    async with httpx.AsyncClient() as client:
        listings = await LeverSource(["shopify"]).search(
            JobQuery(query="python", limit=10), client=client
        )
    assert len(listings) == 1
    listing = listings[0]
    assert listing.title == "Backend Engineer"
    assert listing.company == "Shopify"
    assert listing.employment_type == "full-time"
    assert listing.url == "https://jobs.lever.co/shopify/abc"


@respx.mock
async def test_remotive_http_error_is_propagated_as_http_status_error():
    respx.get("https://remotive.com/api/remote-jobs").respond(status_code=500)
    async with httpx.AsyncClient() as client:
        try:
            await RemotiveSource().search(JobQuery(query="x", limit=5), client=client)
        except httpx.HTTPStatusError:
            pass
        else:
            raise AssertionError("expected HTTPStatusError after retries")
