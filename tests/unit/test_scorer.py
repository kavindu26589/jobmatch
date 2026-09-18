"""Tests for the hybrid matcher (lexical + LLM scoring)."""

from __future__ import annotations

from tests.conftest import FakeGateway, sample_listings, sample_profile

from jobmatcher.domain.enums import Priority
from jobmatcher.domain.models import JobImprovement, JobImprovementAction, LLMJobFit
from jobmatcher.matching import MatchScorer, weighted_jaccard


def test_weighted_jaccard_zero_when_disjoint():
    assert weighted_jaccard({"a": 1}, {"b": 1}) == 0.0


def test_weighted_jaccard_full_overlap():
    assert weighted_jaccard({"a": 2, "b": 1}, {"a": 2, "b": 1}) == 1.0


def test_lexical_scoring_ranks_skills_first(profile):
    listings = sample_listings()
    scorer = MatchScorer(FakeGateway(), "zen", "model")
    scores = {listing.dedupe_key(): scorer.lexical(profile, listing) for listing in listings}
    data_score = scores["greenhouse:g-1"].lexical_score
    frontend_score = scores["greenhouse:g-3"].lexical_score
    assert data_score > frontend_score
    assert "react" in scores["greenhouse:g-3"].missing_skills


def test_lexical_recognizes_matched_skills(profile, listings):
    scorer = MatchScorer(FakeGateway(), "zen", "model")
    score = scorer.lexical(profile, listings[0])
    assert "python" in score.matched_skills
    assert "sql" in score.matched_skills


async def test_fit_score_is_dampened_without_llm(profile, listings):
    scorer = MatchScorer(FakeGateway(), "zen", "model")
    [match] = await scorer.rank(profile, listings[:1], llm_top_n=1, min_score=0)
    assert match.score.llm_score is None
    assert "keyword overlap only" in match.score.reasoning
    assert match.score.improvement is not None
    assert match.score.improvement.actions


async def test_fit_improvement_falls_back_to_keyword_advice(profile, listings):
    scorer = MatchScorer(FakeGateway(), "zen", "model")
    [match] = await scorer.rank(profile, listings[:1], llm_top_n=1, min_score=0)
    missing = match.score.missing_skills[0]
    areas = [action.area for action in match.score.improvement.actions]
    assert "skills" in areas
    assert any(missing in action.advice for action in match.score.improvement.actions)


async def test_rank_carries_llm_improvement_into_score(profile, listings):
    fake = FakeGateway(
        structured={
            "LLMJobFit": lambda user: LLMJobFit(
                fit_score=90.0,
                missing_skills=["kubernetes"],
                reasoning="strong overlap",
                improvement=JobImprovement(
                    summary="Surface clustering work in the summary.",
                    actions=[
                        JobImprovementAction(
                            area="summary",
                            advice="Name kubernetes explicitly if you operated clusters.",
                            original="6 years building web backends",
                            rewritten=(
                                "6 years building and operating Python backends on kubernetes"
                            ),
                            priority=Priority.P0,
                        )
                    ],
                ),
            )
        }
    )
    scorer = MatchScorer(fake, "zen", "model")
    matches = await scorer.rank(profile, listings[:1], llm_top_n=1, min_score=0)
    improvement = matches[0].score.improvement
    assert improvement is not None
    assert improvement.summary == "Surface clustering work in the summary."
    assert improvement.actions[0].area == "summary"
    assert improvement.actions[0].original.startswith("6 years building")
    dumped = matches[0].score.model_dump()
    assert dumped["improvement"]["actions"][0]["rewritten"].endswith("kubernetes")


async def test_rank_blends_llm_fit_when_available(profile, listings):
    fake = FakeGateway(
        structured={
            "LLMJobFit": lambda user: LLMJobFit(
                fit_score=90.0,
                matched_skills=["python", "sql"],
                missing_skills=["kubernetes"],
                overqualified=False,
                reasoning="strong overlap",
            )
        }
    )
    scorer = MatchScorer(fake, "zen", "model")
    matches = await scorer.rank(profile, listings, llm_top_n=3, min_score=0)
    assert len(matches) == len(listings)
    for match in matches:
        assert match.score.llm_score == 90.0
        assert "kubernetes" in match.score.missing_skills
    assert matches[0].rank == 1


async def test_rank_filters_below_min_score(profile, listings):
    fake = FakeGateway(
        structured={"LLMJobFit": lambda user: LLMJobFit(fit_score=5.0, reasoning="poor fit")}
    )
    scorer = MatchScorer(fake, "zen", "model")
    matches = await scorer.rank(profile, listings, llm_top_n=3, min_score=50)
    assert all(match.score.fit_score >= 50 for match in matches)
