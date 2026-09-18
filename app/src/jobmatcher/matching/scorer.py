"""Hybrid job-matching: deterministic lexical scoring + LLM fit scoring."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter

from gateway import LLMGateway
from gateway.errors import GatewayError

from ..domain.enums import Priority
from ..domain.models import (
    JobImprovement,
    JobImprovementAction,
    JobListing,
    JobMatch,
    LLMJobFit,
    MatchScore,
    ResumeProfile,
)
from ..resume.keywords import detect_skills, tokenize
from .llm_fit import LLM_FIT_SYSTEM

logger = logging.getLogger("jobmatcher.matching")

_SKILL_WEIGHT = 4.0


def _fallback_improvement(missing: list[str]) -> JobImprovement:
    """Keyword-based advice for jobs that were only scored lexically."""
    if not missing:
        return JobImprovement(summary="Add or refine a few requirements named by this job.")
    return JobImprovement(
        summary=f"Close the gap on {min(len(missing), 5)} requirement(s) named by this job.",
        actions=[
            JobImprovementAction(
                area="skills",
                advice=(
                    f"Mirror '{keyword}' into the skills section, and back it up in a bullet, "
                    "only where it is genuinely true for you."
                ),
                priority=Priority.P1,
            )
            for keyword in missing[:5]
        ],
    )


def _tokens(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def weighted_jaccard(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    overlap = sum(min(a[key], b[key]) for key in set(a) & set(b))
    union = sum(a.values()) + sum(b.values()) - overlap
    return overlap / union if union else 0.0


class MatchScorer:
    """Ranks job listings against a candidate profile.

    Every listing receives a deterministic lexical score; the top ``llm_top_n``
    are additionally scored by the model, and the two are blended 50/50.
    """

    def __init__(self, gateway: LLMGateway, provider: str, model: str) -> None:
        self.gateway = gateway
        self.provider = provider
        self.model = model

    def lexical(self, profile: ResumeProfile, listing: JobListing) -> MatchScore:
        skills = profile.all_skills()
        job_text = listing.searchable_text().lower()
        matched = [skill for skill in skills if skill in job_text]

        skill_score = 100.0 * len(matched) / len(skills) if skills else 0.0

        profile_bag = _tokens(profile.condensed())
        for skill in profile.all_skills():
            profile_bag.update(tokenize(skill) * int(_SKILL_WEIGHT))
            profile_bag.update(tokenize(skill))
        job_bag = _tokens(job_text)
        jaccard = weighted_jaccard(profile_bag, job_bag)

        title_tokens = _tokens(listing.title)
        title_overlap = sum(
            min(title_tokens[key], job_bag[key]) for key in set(title_tokens) & set(job_bag)
        )

        lexical = round(
            min(
                100.0,
                0.6 * skill_score
                + 0.3 * (jaccard * 100.0)
                + 0.1 * min(100.0, title_overlap * 12.0),
            ),
            2,
        )
        missing = [skill for skill in detect_skills(listing.description) if skill not in skills][
            :15
        ]
        return MatchScore(
            job_key=listing.dedupe_key(),
            fit_score=lexical,
            lexical_score=lexical,
            matched_skills=matched[:20],
            missing_skills=missing,
        )

    async def _llm_fit(self, profile: ResumeProfile, listing: JobListing) -> LLMJobFit | None:
        job_snippet = listing.searchable_text()[:1400]
        user = f"PROFILE\n{profile.condensed()}\n\nJOB\n{job_snippet}"
        try:
            return await self.gateway.structured(
                self.provider,
                self.model,
                schema=LLMJobFit,
                system=LLM_FIT_SYSTEM,
                user=user,
            )
        except GatewayError as exc:
            logger.warning("LLM fit scoring failed for %s: %s", listing.dedupe_key(), exc)
            return None

    async def rank(
        self,
        profile: ResumeProfile,
        listings: list[JobListing],
        *,
        llm_top_n: int = 15,
        min_score: float = 30.0,
    ) -> list[JobMatch]:
        scores = [self.lexical(profile, listing) for listing in listings]
        ranked_indices = sorted(
            range(len(listings)), key=lambda i: scores[i].lexical_score, reverse=True
        )
        top_indices = ranked_indices[: max(1, llm_top_n)]
        fits = await asyncio.gather(*(self._llm_fit(profile, listings[i]) for i in top_indices))
        fit_by_index = dict(zip(top_indices, fits, strict=False))

        matches: list[JobMatch] = []
        for index, listing in enumerate(listings):
            score = scores[index]
            fit = fit_by_index.get(index)
            if fit is None:
                score.fit_score = round(score.lexical_score * 0.8, 2)
                score.reasoning = "Scored by keyword overlap only (LLM scoring unavailable)."
                score.improvement = _fallback_improvement(score.missing_skills)
            else:
                score.llm_score = fit.fit_score
                score.fit_score = round(
                    min(100.0, 0.5 * score.lexical_score + 0.5 * fit.fit_score), 2
                )
                score.matched_skills = list(
                    dict.fromkeys(score.matched_skills + fit.matched_skills)
                )[:20]
                score.missing_skills = list(
                    dict.fromkeys(score.missing_skills + fit.missing_skills)
                )[:15]
                score.overqualified = fit.overqualified
                score.reasoning = fit.reasoning
                score.improvement = (
                    fit.improvement
                    if fit.improvement.actions
                    else _fallback_improvement(score.missing_skills)
                )
            if score.fit_score >= min_score:
                matches.append(
                    JobMatch(
                        listing=listing,
                        score=score,
                        rank=len(matches) + 1,
                    )
                )
        matches.sort(key=lambda match: match.score.fit_score, reverse=True)
        for rank, match in enumerate(matches, start=1):
            match.rank = rank
        return matches
