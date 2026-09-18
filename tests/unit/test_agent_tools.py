"""Tests for the agent tool layer (ReAct tools on a shared session)."""

from __future__ import annotations

from tests.conftest import SAMPLE_RESUME, FakeContext, FakeGateway, sample_profile, sample_report

from jobmatcher.agents.tools import AGENT_TOOLS, TOOL_HANDLERS
from jobmatcher.domain.models import LLMJobFit


async def test_tool_registry_covers_specs():
    assert set(TOOL_HANDLERS) == {tool.name for tool in AGENT_TOOLS}


async def test_search_jobs_populates_session(fake_context):
    result = await TOOL_HANDLERS["search_jobs"](
        fake_context, {"query": "data engineer", "limit": 5}
    )
    assert result["found"] == 3
    assert len(fake_context.session["listings"]) == 3


async def test_analyze_resume_requires_path(fake_context):
    result = await TOOL_HANDLERS["analyze_resume"](fake_context, {})
    assert result["error"]


async def test_analyze_resume_reads_file(tmp_path, fake_context: FakeContext):
    fake_context.gateway = FakeGateway(structured={"ResumeProfileStructured": sample_profile()})
    path = tmp_path / "resume.txt"
    path.write_text(SAMPLE_RESUME, encoding="utf-8")
    result = await TOOL_HANDLERS["analyze_resume"](fake_context, {"path": str(path)})
    assert result["name"] == "Jane Doe"
    assert fake_context.session["profile"] is not None


async def test_analyze_fit_needs_profile_and_jobs(fake_context):
    result = await TOOL_HANDLERS["analyze_fit"](fake_context, {})
    assert result["error"]
    fake_context.session["profile"] = sample_profile()
    result = await TOOL_HANDLERS["analyze_fit"](fake_context, {"num_jobs": 3})
    assert result["error"]  # still no listings


async def test_analyze_fit_scores_listings(fake_context):
    fake_context.session["profile"] = sample_profile()
    fake_context.session["listings"] = fake_context._listings
    fake_context.gateway = FakeGateway(
        structured={
            "LLMJobFit": lambda user: LLMJobFit(
                fit_score=88.0, missing_skills=["kubernetes"], reasoning="fit"
            )
        }
    )
    result = await TOOL_HANDLERS["analyze_fit"](fake_context, {"num_jobs": 3})
    assert result["top_matches"]
    assert fake_context.session["matches"]


async def test_improve_resume_requires_profile_and_matches(fake_context):
    result = await TOOL_HANDLERS["improve_resume"](fake_context, {})
    assert result["error"]


async def test_improve_resume_produces_report(fake_context):
    fake_context.gateway = FakeGateway(
        structured={
            "ResumeImprovementReport": sample_report(),
            "LLMJobFit": lambda user: LLMJobFit(fit_score=80, reasoning="ok"),
        }
    )
    fake_context.session["profile"] = sample_profile()
    fake_context.session["listings"] = fake_context._listings
    await TOOL_HANDLERS["analyze_fit"](fake_context, {"num_jobs": 3})
    result = await TOOL_HANDLERS["improve_resume"](fake_context, {"num_targets": 2})
    assert result["ats_score"] == 72.0
    assert fake_context.session["report"] is not None
