"""Tests for report rendering and persistence."""

from __future__ import annotations

import json

from tests.conftest import sample_listings, sample_profile, sample_report

from jobmatcher.domain.models import MatchResult
from jobmatcher.report import render_improvement, render_matches, render_report, save_report


def _clean_result() -> MatchResult:
    from jobmatcher.domain.models import JobMatch, MatchScore

    listings = sample_listings()
    return MatchResult(
        profile=sample_profile(),
        jobs_retrieved=len(listings),
        matches=[
            JobMatch(
                listing=listing,
                score=MatchScore(job_key=listing.dedupe_key(), fit_score=77.5),
                rank=i + 1,
            )
            for i, listing in enumerate(listings)
        ],
        improvement=sample_report(),
    )


def test_render_matches_lists_titles():
    markdown = render_matches(_clean_result())
    assert "Data Engineer" in markdown
    assert "Frontend Engineer" in markdown
    assert "78" in markdown


def test_render_improvement_shows_keywords_and_actions():
    markdown = render_improvement(_clean_result())
    assert "kubernetes" in markdown
    assert "Add Kubernetes under skills" in markdown
    assert "ATS score" in markdown


def test_render_report_empty_matches():
    result = MatchResult(profile=None, jobs_retrieved=0, matches=[], improvement=None)
    markdown = render_report(result)
    assert "No matches above the minimum score" in markdown
    assert "No improvement report produced" in markdown


def test_save_report_writes_markdown_and_json(tmp_path):
    md_path, json_path = save_report(_clean_result(), tmp_path)
    assert md_path.exists() and json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["jobs_retrieved"] == 3
    assert payload["improvement"]["overall_ats_score"] == 72.0
    assert "Job match report" in md_path.read_text(encoding="utf-8")


def test_agent_transcript_rendered():
    result = _clean_result().model_copy(
        update={
            "agent_transcript": [
                {"role": "user", "content": "Find data jobs"},
                {"role": "assistant", "content": "Done"},
            ]
        }
    )
    markdown = render_report(result)
    assert "Agent transcript" in markdown
    assert "Find data jobs" in markdown


def test_render_improvement_none():
    assert render_improvement(MatchResult()) == "_No improvement report produced._"
