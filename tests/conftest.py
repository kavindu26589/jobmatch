"""Shared fixtures for jobmatcher application tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from gateway.protocols import ChatResult, Message, ToolCall
from gateway.usage import Usage
from jobmatcher.agents.improver import ResumeImprover
from jobmatcher.domain.models import JobListing, ResumeImprovementReport, ResumeProfile
from jobmatcher.matching import MatchScorer
from jobmatcher.resume.extractor import ResumeExtractor

SAMPLE_RESUME = (
    "Jane Doe\njane@example.com | 555-123-4567 | linkedin.com/in/janedoe\n\n"
    "SUMMARY\nSoftware engineer with 5 years building data pipelines in Python.\n\n"
    "SKILLS\nPython, pandas, SQL, Docker, AWS, machine learning, git\n\n"
    "EXPERIENCE\nData Engineer at Acme (2020 - 2023)\n"
    "- Built ETL pipelines processing 20TB nightly\n"
    "Backend Engineer at Globex (2018 - 2020)\n"
    "- Maintained REST APIs in Python\n\n"
    "EDUCATION\nBS Computer Science, State University\n"
)


def sample_profile(**overrides: Any) -> ResumeProfile:
    data = dict(
        contact={
            "name": "Jane Doe",
            "email": "jane@example.com",
            "linkedin": "linkedin.com/in/janedoe",
        },
        summary="Software engineer with 5 years building data pipelines in Python.",
        hard_skills=["python", "pandas", "sql", "docker", "aws", "machine learning"],
        soft_skills=["collaboration"],
        target_titles=["Data Engineer", "Backend Engineer"],
        years_experience=5.0,
        experience=[
            {
                "title": "Data Engineer",
                "company": "Acme",
                "start_date": "2020",
                "end_date": "2023",
                "bullets": ["Built ETL pipelines processing 20TB nightly"],
            }
        ],
        raw_text=SAMPLE_RESUME,
    )
    data.update(overrides)
    return ResumeProfile.model_validate(data)


def sample_listings() -> list[JobListing]:
    return [
        JobListing(
            external_id="g-1",
            source="greenhouse",
            title="Data Engineer",
            company="Acme",
            location="Remote",
            description=(
                "We need a Data Engineer skilled in Python, pandas, SQL and AWS to "
                "build and maintain ETL pipelines. Git and Docker are a plus."
            ),
            url="https://boards.greenhouse.io/acme/jobs/1",
        ),
        JobListing(
            external_id="g-2",
            source="greenhouse",
            title="Backend Engineer",
            company="Globex",
            location="Berlin",
            description="Python REST APIs with PostgreSQL, Redis and Kubernetes.",
            url="https://boards.greenhouse.io/globex/jobs/2",
        ),
        JobListing(
            external_id="g-3",
            source="greenhouse",
            title="Frontend Engineer",
            company="Initech",
            location="Remote",
            description="React, TypeScript and CSS. No backend experience required.",
            url="https://boards.greenhouse.io/initech/jobs/3",
        ),
    ]


def sample_report(**overrides: Any) -> ResumeImprovementReport:
    from jobmatcher.domain.enums import Importance, Priority

    data = dict(
        overall_ats_score=72.0,
        summary="Resume is decent but under-uses job keywords like Kubernetes.",
        sections=[],
        missing_keywords=[
            {"keyword": "kubernetes", "appears_in_targets": 2, "importance": Importance.HIGH}
        ],
        priority_actions=[
            {"priority": Priority.P0, "action": "Add Kubernetes under skills."},
            {"priority": Priority.P1, "action": "Quantify ETL pipeline results."},
        ],
        target_titles=["Data Engineer", "Backend Engineer"],
    )
    data.update(overrides)
    return ResumeImprovementReport.model_validate(data)


class FakeGateway:
    """Duck-typed stand-in for ``gateway.LLMGateway`` (no network, no keys).

    ``structured`` returns whatever was registered under the schema class name;
    entries may be instances or (user_text) -> instance callables.
    ``chat`` pops from ``chat_results`` in order; the default is a final answer.
    """

    def __init__(
        self,
        structured: dict[str, Any | Callable[[str], Any]] | None = None,
        chat_results: list[ChatResult] | None = None,
    ) -> None:
        self._structured = structured or {}
        self.chat_results = list(chat_results or [])
        self.structured_calls: list[tuple[str, str, str, str]] = []
        self.chat_calls: list[tuple[str, str, list[Message], object]] = []

    async def structured(
        self,
        provider_id: str,
        model_id: str,
        *,
        schema: type,
        system: str = "",
        user: str = "",
        **_: Any,
    ) -> Any:
        self.structured_calls.append((provider_id, model_id, schema.__name__, user))
        entry = self._structured.get(schema.__name__)
        if entry is None:
            return None
        return entry(user) if callable(entry) else entry

    async def chat(
        self,
        provider_id: str,
        model_id: str,
        messages: list[Message],
        *,
        tools: list[object] | None = None,
        **_: Any,
    ) -> ChatResult:
        self.chat_calls.append((provider_id, model_id, list(messages), tools))
        if self.chat_results:
            return self.chat_results.pop(0)
        return ChatResult(
            content="Final answer.",
            tool_calls=[],
            usage=Usage(input_tokens=2, output_tokens=3),
            finish_reason="stop",
            raw={},
        )

    def usage_snapshot(self) -> list[object]:
        return []

    def total_cost(self) -> float:
        return 0.0


def tool_call_result(name: str, arguments: dict[str, Any] | None = None) -> ChatResult:
    return ChatResult(
        content="",
        tool_calls=[
            ToolCall(
                id="call_1",
                name=name,
                arguments=arguments or {},
                raw="",
            )
        ],
        usage=Usage(input_tokens=1, output_tokens=1),
        finish_reason="tool_calls",
        raw={},
    )


def final_answer_result(content: str = "Here are your matches.") -> ChatResult:
    return ChatResult(
        content=content,
        tool_calls=[],
        usage=Usage(input_tokens=1, output_tokens=1),
        finish_reason="stop",
        raw={},
    )


class FakeContext:
    """Minimal service for graphs/tools that provides all domain components."""

    provider = "zen"
    model = "gpt-test"

    def __init__(
        self,
        gateway: FakeGateway,
        listings: list[JobListing] | None = None,
    ) -> None:
        self.gateway = gateway
        self.session: dict[str, Any] = {}
        self._listings = listings or []

    async def search_jobs(self, request: JobListing) -> tuple[list[JobListing], list[str]]:
        return self._listings, []

    def extractor(self) -> ResumeExtractor:
        return ResumeExtractor(self.gateway, self.provider, self.model)

    def scorer(self) -> MatchScorer:
        return MatchScorer(self.gateway, self.provider, self.model)

    def improver(self) -> ResumeImprover:
        return ResumeImprover(self.gateway, self.provider, self.model)


@pytest.fixture
def resume_text() -> str:
    return SAMPLE_RESUME


@pytest.fixture
def profile() -> ResumeProfile:
    return sample_profile()


@pytest.fixture
def listings() -> list[JobListing]:
    return sample_listings()


@pytest.fixture
def report() -> ResumeImprovementReport:
    return sample_report()


@pytest.fixture
def fake_gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def fake_context(fake_gateway: FakeGateway) -> FakeContext:
    return FakeContext(fake_gateway, listings=sample_listings())
