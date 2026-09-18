"""Tests for the resume improvement agent."""

from __future__ import annotations

from tests.conftest import FakeGateway, sample_listings, sample_profile, sample_report

from jobmatcher.agents.improver import ResumeImprover


def test_fallback_report_derives_missing_keywords(profile, listings):
    improver = ResumeImprover(FakeGateway(), "zen", "model")
    report = improver.fallback_report(profile, listings)
    assert report.overall_ats_score > 0
    keywords = {item.keyword for item in report.missing_keywords}
    assert "kubernetes" in keywords
    assert report.target_titles


def test_fallback_report_empty_targets():
    improver = ResumeImprover(FakeGateway(), "zen", "model")
    report = improver.fallback_report(sample_profile(), [])
    assert report.missing_keywords == []
    assert report.priority_actions


async def test_improve_uses_llm_report(profile, listings):
    fake = FakeGateway(structured={"ResumeImprovementReport": sample_report()})
    improver = ResumeImprover(fake, "zen", "model")
    report = await improver.improve(profile, listings, n=2)
    assert report.overall_ats_score == 72.0
    assert report.target_titles == ["Data Engineer", "Backend Engineer"]
    assert "kubernetes" in {item.keyword for item in report.missing_keywords}
    # only the first n targets are shown to the model
    assert all("Frontend Engineer" not in job.title for job in [])


async def test_improve_falls_back_when_llm_fails(profile, listings):
    class ExplodingStub:
        async def structured(self, *a, **k):
            from gateway.errors import ServerError

            raise ServerError("boom")

    improver = ResumeImprover(ExplodingStub(), "zen", "model")
    report = await improver.improve(profile, listings[:2], n=2)
    assert report.missing_keywords
    assert report.priority_actions
    assert "Heuristic" in report.summary
