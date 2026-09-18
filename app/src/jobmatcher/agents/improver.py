"""Resume improvement agent: diagnoses weaknesses and prescribes concrete edits."""

from __future__ import annotations

import logging
from collections import Counter

from gateway import LLMGateway
from gateway.errors import GatewayError

from ..domain.enums import Importance, Priority
from ..domain.models import (
    JobListing,
    MissingKeyword,
    PriorityAction,
    ResumeImprovementReport,
    ResumeProfile,
    SectionReview,
)
from ..resume.keywords import detect_skills

logger = logging.getLogger("jobmatcher.improver")

IMPROVEMENT_SYSTEM = """You are a senior career coach and ATS-optimization expert.

Given a candidate profile and the target jobs they want, produce the required
JSON schema (emit_json) for a resume improvement report:
- overall_ats_score: 0-100 readability for modern ATS + recruiters.
- summary: a 2-4 sentence diagnosis of the resume's biggest weaknesses.
- sections: per relevant resume section (summary, skills, experience, education,
  projects) with strengths, issues, and concrete suggestions. Each suggestion
  carries an optional 'original' (the problematic text) and a rewritten version,
  the rationale, and a priority P0/P1/P2 (P0 = do first).
- missing_keywords: job-description keywords the resume lacks or under-uses,
  each with appears_in_targets (how many targets mention it) and importance.
- priority_actions: 5-8 ordered, concrete, actionable steps (P0/P1/P2).
- target_titles: the job titles this profile is being optimized for.

Never invent projects or employers. Rewrites must be plausible, honest
improvements of the candidate's real content."""

_TARGET_DESC_LIMIT = 1000


class ResumeImprover:
    def __init__(self, gateway: LLMGateway, provider: str, model: str) -> None:
        self.gateway = gateway
        self.provider = provider
        self.model = model

    async def improve(
        self,
        profile: ResumeProfile,
        targets: list[JobListing],
        *,
        n: int = 3,
    ) -> ResumeImprovementReport:
        selected = targets[:n]
        if not selected:
            report = self.fallback_report(profile, selected)
            report.summary = "No target jobs supplied; report is keyword-based only."
            return report
        jobs_block = "\n\n".join(
            f"[{i + 1}] {job.title} | {job.company} | {job.location}\n"
            f"{job.description[:_TARGET_DESC_LIMIT]}"
            for i, job in enumerate(selected)
        )
        user = f"PROFILE\n{profile.to_llm_json()}\n\nTARGET JOBS\n{jobs_block}"
        try:
            report = await self.gateway.structured(
                self.provider,
                self.model,
                schema=ResumeImprovementReport,
                system=IMPROVEMENT_SYSTEM,
                user=user,
            )
        except GatewayError as exc:
            logger.warning(
                "LLM improvement report failed (%s); using heuristic fallback", type(exc).__name__
            )
            report = self.fallback_report(profile, selected)
        return report

    def fallback_report(
        self, profile: ResumeProfile, targets: list[JobListing]
    ) -> ResumeImprovementReport:
        skills = profile.all_skills()
        counted = Counter(
            skill
            for job in targets
            for skill in detect_skills(job.description)
            if skill not in skills
        )
        total = max(len(targets), 1)
        missing = [
            MissingKeyword(
                keyword=keyword,
                appears_in_targets=count,
                importance=Importance.HIGH if count >= max(1, total // 2) else Importance.MEDIUM,
            )
            for keyword, count in counted.most_common(12)
        ]
        overall = round(max(0.0, min(100.0, 55.0 + 15.0 * len(targets))))
        return ResumeImprovementReport(
            overall_ats_score=overall,
            summary=(
                "Heuristic analysis (LLM unavailable): resume lacks several keywords used "
                "by the target jobs; add them honestly where true."
            ),
            sections=[
                SectionReview(
                    section="skills",
                    issues=[
                        (
                            f"missing or under-using: "
                            f"{', '.join(k.keyword for k in missing[:8]) or 'none detected'}"
                        )
                    ],
                )
            ],
            missing_keywords=missing,
            priority_actions=[
                PriorityAction(
                    priority=Priority.P0,
                    action="Mirror target-job keywords into the skills section where accurate.",
                ),
                PriorityAction(
                    priority=Priority.P1,
                    action="Rewrite the summary to name the target role and top 3 strengths.",
                ),
                PriorityAction(
                    priority=Priority.P2,
                    action="Quantify results in experience bullets (%, $, volume).",
                ),
            ],
            target_titles=[job.title for job in targets[:4]],
        )
