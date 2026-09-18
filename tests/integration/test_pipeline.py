"""Integration tests: LangGraph pipeline + ReAct agent with a fake model."""

from __future__ import annotations

from tests.conftest import (
    SAMPLE_RESUME,
    FakeContext,
    FakeGateway,
    final_answer_result,
    sample_profile,
    sample_report,
    tool_call_result,
)

from jobmatcher.agents.graph import build_agent, build_pipeline
from jobmatcher.domain.models import LLMJobFit, MatchRequest


def _full_gateway() -> FakeGateway:
    return FakeGateway(
        structured={
            "ResumeProfileStructured": sample_profile(),
            "LLMJobFit": lambda user: LLMJobFit(
                fit_score=82.0, missing_skills=["kubernetes"], reasoning="solid"
            ),
            "ResumeImprovementReport": sample_report(),
        }
    )


async def test_pipeline_end_to_end(fake_context: FakeContext):
    fake_context.gateway = _full_gateway()
    graph = build_pipeline(fake_context)
    request = MatchRequest(
        resume_text=SAMPLE_RESUME, query="data", limit=3, llm_top_n=3, min_score=0
    )
    final = await graph.ainvoke({"request": request})
    result = final["result"]
    assert result.profile is not None
    assert result.jobs_retrieved == 3
    assert result.matches
    assert result.matches[0].rank == 1
    assert result.improvement is not None
    assert result.improvement.overall_ats_score == 72.0


async def test_pipeline_skips_search_on_resume_error(fake_context):
    fake_context.gateway = _full_gateway()
    graph = build_pipeline(fake_context)
    request = MatchRequest(query="anything", limit=3)
    final = await graph.ainvoke({"request": request})
    result = final["result"]
    assert result.jobs_retrieved == 0
    assert any("resume text" in warning for warning in result.warnings)


async def test_pipeline_improve_skippable(fake_context):
    fake_context.gateway = _full_gateway()
    graph = build_pipeline(fake_context)
    request = MatchRequest(resume_text=SAMPLE_RESUME, query="data", improve=False, min_score=0)
    final = await graph.ainvoke({"request": request})
    result = final["result"]
    assert result.matches
    assert result.improvement is None


async def test_agent_uses_tools_then_answers(tmp_path, fake_context: FakeContext):
    resume = tmp_path / "resume.txt"
    resume.write_text(SAMPLE_RESUME, encoding="utf-8")
    fake_context.gateway = FakeGateway(
        structured={"ResumeProfileStructured": sample_profile()},
        chat_results=[
            tool_call_result("analyze_resume", {"path": str(resume)}),
            final_answer_result("Top match: Data Engineer at Acme."),
        ],
    )
    graph = build_agent(fake_context)
    request = MatchRequest(resume_path=str(resume), query="data", limit=3)
    final = await graph.ainvoke(
        {
            "request": request,
            "messages": [{"role": "user", "content": "Evaluate my resume for data jobs."}],
            "steps": 0,
            "final": False,
        }
    )
    result = final["result"]
    assert result.profile is not None
    assert result.profile.contact.name == "Jane Doe"
    assert result.agent_transcript
    assert fake_context.session["final_answer"] == "Top match: Data Engineer at Acme."
    assert fake_context.gateway.chat_calls


async def test_agent_fails_gracefully_on_tool_error(fake_context):
    fake_context.gateway = FakeGateway(
        chat_results=[
            tool_call_result("analyze_resume", {"path": "C:/missing/resume.pdf"}),
            final_answer_result("No resume found, please supply a file."),
        ],
    )
    graph = build_agent(fake_context)
    request = MatchRequest(resume_text=SAMPLE_RESUME, query="data", limit=3)
    final = await graph.ainvoke(
        {
            "request": request,
            "messages": [{"role": "user", "content": "Please analyze."}],
            "steps": 0,
            "final": False,
        }
    )
    result = final["result"]
    assert result.agent_transcript
    # the failed tool produced an error payload but the agent still completed
    assert fake_context.session.get("final_answer") == "No resume found, please supply a file."
