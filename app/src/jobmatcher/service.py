"""Application wiring: builds the gateway, sources, and orchestration graphs.

``JobMatchService`` is the single entry point used by the CLI, the HTTP server,
and the unit/integration tests. All heavy components are built lazily and cached
so a worker process reuses them across requests.
"""

from __future__ import annotations

import logging
from typing import Any

from gateway import LLMGateway
from gateway.client import AsyncRateLimiter, CircuitBreaker
from gateway.providers import build_registry
from gateway.usage import UsageLedger

from .agents.improver import ResumeImprover
from .agents.tools import skills_preview  # noqa: F401 (re-exported convenience)
from .config import Settings, get_settings
from .domain.models import (
    JobListing,
    MatchRequest,
    MatchResult,
    ResumeAnalysis,
    SearchResult,
)
from .jobs.searcher import JobSearcher
from .jobs.sources import SOURCE_IDS, JobQuery, create_job_sources
from .matching import MatchScorer
from .resume.extractor import ResumeExtractor

logger = logging.getLogger("jobmatcher.service")


def build_gateway(settings: Settings | None = None) -> LLMGateway:
    """Create an LLM gateway from application settings.

    Uses opencode-compatible configuration by default: the ``zen`` provider reads
    ``OPENCODE_API_KEY`` and speaks the OpenAI-compatible protocol; caller models
    and base URLs are overrideable via settings.
    """
    settings = settings or get_settings()
    env = settings.gateway_env()
    registry = build_registry(env=env)
    if settings.gateway_base_url:
        registry.get(settings.gateway_provider).base_url = settings.gateway_base_url.rstrip("/")
    ledger = UsageLedger(budget_usd=settings.llm_cost_limit_usd)
    limiter = AsyncRateLimiter(
        capacity=settings.llm_max_concurrency,
        refill_per_second=settings.llm_max_concurrency,
    )
    return LLMGateway(
        registry,
        env=env,
        default_max_attempts=settings.llm_max_retries,
        rate_limiter=limiter,
        ledger=ledger,
        breaker=CircuitBreaker(failure_threshold=5, reset_after=30.0),
    )


class JobMatchService:
    """Wires settings -> gateway -> sources -> components -> graphs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.provider = self.settings.gateway_provider
        self.model = self.settings.gateway_model
        self.session: dict[str, Any] = {}
        self._gateway: LLMGateway | None = None
        self._extractor: ResumeExtractor | None = None
        self._scorer: MatchScorer | None = None
        self._improver: ResumeImprover | None = None
        self._pipeline: Any | None = None
        self._agent_graph: Any | None = None

    # -- component accessors -------------------------------------------------

    @property
    def gateway(self) -> LLMGateway:
        if self._gateway is None:
            self._gateway = build_gateway(self.settings)
        return self._gateway

    def extractor(self) -> ResumeExtractor:
        if self._extractor is None:
            self._extractor = ResumeExtractor(self.gateway, self.provider, self.model)
        return self._extractor

    def scorer(self) -> MatchScorer:
        if self._scorer is None:
            self._scorer = MatchScorer(self.gateway, self.provider, self.model)
        return self._scorer

    def improver(self) -> ResumeImprover:
        if self._improver is None:
            self._improver = ResumeImprover(self.gateway, self.provider, self.model)
        return self._improver

    # -- graphs --------------------------------------------------------------

    def pipeline(self) -> Any:
        from .agents.graph import build_pipeline

        if self._pipeline is None:
            self._pipeline = build_pipeline(self)
        return self._pipeline

    def agent_graph(self) -> Any:
        from .agents.graph import build_agent

        if self._agent_graph is None:
            self._agent_graph = build_agent(self)
        return self._agent_graph

    # -- operations ----------------------------------------------------------

    async def search_jobs(self, request: MatchRequest) -> tuple[list[JobListing], list[str]]:
        """Fetch listings from the configured internet sources concurrently."""
        query = JobQuery(
            query=request.query,
            location=request.location,
            remote_only=request.remote_only,
            limit=request.limit,
        )
        sources = create_job_sources(
            request.sources or self.settings.job_source_ids,
            greenhouse_boards=self.settings.greenhouse_boards,
            lever_companies=self.settings.lever_companies,
            usajobs_api_key=self.settings.usajobs_api_key,
            usajobs_email=self.settings.usajobs_email,
        )
        async with JobSearcher(sources) as searcher:
            return await searcher.search(query)

    async def analyze(self, resume_text: str) -> ResumeAnalysis:
        """Parse a resume into a structured profile (LLM + heuristics)."""
        profile, warnings = await self.extractor().extract(resume_text)
        return ResumeAnalysis(
            profile=profile,
            warnings=warnings,
            usage=[record.as_dict() for record in self.gateway.usage_snapshot()],
        )

    async def search(self, request: MatchRequest) -> SearchResult:
        """Public search returning listings only (no matching)."""
        listings, warnings = await self.search_jobs(request)
        return SearchResult(jobs_retrieved=len(listings), listings=listings, warnings=warnings)

    async def match(self, request: MatchRequest) -> MatchResult:
        """Full pipeline: analyze resume -> fetch jobs -> score -> improve."""
        self.session = {}
        final = await self.pipeline().ainvoke({"request": request})
        return final.get("result") or self._empty_result()

    async def agent(self, request: MatchRequest, question: str = "") -> MatchResult:
        """ReAct agent that plans its own tool calls for a natural-language goal."""
        self.session = {}
        self.session.setdefault("warnings", [])
        prompt = question.strip() or (
            "Analyze the linked resume, find the best-matching live jobs, "
            "score them, and produce a resume improvement plan."
        )
        resume_hint = ""
        if request.resume_path:
            resume_hint = (
                f"The candidate's resume is available locally at: {request.resume_path}\n\n"
            )
        initial = {
            "request": request,
            "messages": [{"role": "user", "content": f"{resume_hint}{prompt}"}],
            "steps": 0,
            "final": False,
        }
        final = await self.agent_graph().ainvoke(initial)
        return final.get("result") or self._empty_result()

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _empty_result() -> MatchResult:
        return MatchResult(profile=None, warnings=["no result produced by the agent"], matches=[])

    def _reset_session(self) -> dict[str, Any]:
        self.session = {}
        return self.session


__all__ = ["SOURCE_IDS", "JobMatchService", "Settings", "build_gateway"]
