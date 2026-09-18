"""Core domain models: resume, jobs, matches, and improvement reports.

Every model is a pydantic object so boundaries between layers are explicit and
results serialize cleanly to JSON for the CLI and the HTTP API.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .enums import Importance, Priority

_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower()))


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


class ContactInfo(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class ExperienceEntry(BaseModel):
    title: str = ""
    company: str = ""
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    bullets: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    degree: str = ""
    institution: str = ""
    start_date: str | None = None
    end_date: str | None = None
    details: list[str] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    name: str = ""
    description: str = ""
    technologies: list[str] = Field(default_factory=list)


class CertificationEntry(BaseModel):
    name: str = ""
    issuer: str | None = None
    year: str | None = None


class ResumeProfile(BaseModel):
    contact: ContactInfo = Field(default_factory=ContactInfo)
    summary: str = ""
    hard_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    years_experience: float | None = None
    target_titles: list[str] = Field(default_factory=list)
    raw_text: str = Field(default="", repr=False)

    def all_skills(self) -> set[str]:
        return {s.strip().lower() for s in self.hard_skills + self.soft_skills if s.strip()}

    def keyword_bag(self) -> set[str]:
        """A lexical keyword bag over skills, certifications, and experience text."""
        words: set[str] = set()
        for skill in self.all_skills():
            words.update(_WORD_RE.findall(skill))
        for cert in self.certifications:
            words.update(_WORD_RE.findall(cert.name))
        for project in self.projects:
            words.update(_WORD_RE.findall(project.name))
            for tech in project.technologies:
                words.update(_WORD_RE.findall(tech))
        for item in self.experience:
            words.update(_WORD_RE.findall(item.title))
            words.update(_WORD_RE.findall(item.company))
        return words

    def condensed(self, *, max_chars: int = 2400) -> str:
        """A compact single-string summary used in LLM prompts."""
        parts = [self.summary.strip()]
        skills = ", ".join(sorted(self.all_skills()))
        if skills:
            parts.append(f"Skills: {skills}")
        if self.years_experience is not None:
            parts.append(f"Years of experience: {self.years_experience}")
        for exp in self.experience[:8]:
            parts.append(
                f"{exp.title} at {exp.company} ({exp.start_date} - {exp.end_date or 'present'})"
            )
        if self.target_titles:
            parts.append(f"Target titles: {', '.join(self.target_titles)}")
        return "\n".join(parts)[:max_chars]

    def to_llm_json(self) -> str:
        return self.model_dump_json(exclude={"raw_text"}, exclude_defaults=True, indent=0)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class JobListing(BaseModel):
    external_id: str
    source: str
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    url: str = ""
    salary: str | None = None
    employment_type: str | None = None
    posted_at: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    def dedupe_key(self) -> str:
        return f"{self.source}:{self.external_id}"

    def normalized_key(self) -> str:
        return f"{_norm(self.company)}|{_norm(self.title)}|{self.location.strip().lower()}"

    def searchable_text(self) -> str:
        return f"{self.title} {self.company} {self.location}\n{self.description}"


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class JobImprovementAction(BaseModel):
    """One concrete change the candidate can make to their CV for a given job."""

    area: str = ""
    advice: str = ""
    original: str = ""
    rewritten: str = ""
    priority: Priority = Priority.P1


class JobImprovement(BaseModel):
    """Per-job guidance: which CV parts to update to best match the posting."""

    summary: str = ""
    actions: list[JobImprovementAction] = Field(default_factory=list)


class MatchScore(BaseModel):
    job_key: str
    fit_score: float = Field(default=0.0, ge=0, le=100)
    lexical_score: float = Field(default=0.0, ge=0, le=100)
    llm_score: float | None = Field(default=None, ge=0, le=100)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    overqualified: bool = False
    reasoning: str = ""
    improvement: JobImprovement | None = None


class JobMatch(BaseModel):
    listing: JobListing
    score: MatchScore
    rank: int | None = None


# ---------------------------------------------------------------------------
# Improvement report
# ---------------------------------------------------------------------------


class RewriteSuggestion(BaseModel):
    section: str
    original: str = ""
    rewritten: str
    rationale: str
    priority: Priority = Priority.P1


class SectionReview(BaseModel):
    section: str
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[RewriteSuggestion] = Field(default_factory=list)


class MissingKeyword(BaseModel):
    keyword: str
    appears_in_targets: int
    importance: Importance = Importance.MEDIUM


class PriorityAction(BaseModel):
    priority: Priority
    action: str


class ResumeImprovementReport(BaseModel):
    overall_ats_score: float = Field(ge=0, le=100)
    summary: str = ""
    sections: list[SectionReview] = Field(default_factory=list)
    missing_keywords: list[MissingKeyword] = Field(default_factory=list)
    priority_actions: list[PriorityAction] = Field(default_factory=list)
    target_titles: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Orchestration inputs / outputs
# ---------------------------------------------------------------------------


class MatchRequest(BaseModel):
    resume_path: str | None = None
    resume_text: str | None = None
    query: str = ""
    location: str = ""
    remote_only: bool = False
    limit: int = 50
    llm_top_n: int = 15
    min_score: float = 30.0
    improve: bool = True
    sources: list[str] | None = None


class MatchResult(BaseModel):
    profile: ResumeProfile | None = None
    jobs_retrieved: int = 0
    matches: list[JobMatch] = Field(default_factory=list)
    improvement: ResumeImprovementReport | None = None
    warnings: list[str] = Field(default_factory=list)
    usage: list[dict[str, object]] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    generated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    agent_transcript: list[dict[str, Any]] = Field(default_factory=list)


class ResumeAnalysis(BaseModel):
    profile: ResumeProfile
    warnings: list[str] = Field(default_factory=list)
    usage: list[dict[str, object]] = Field(default_factory=list)


class SearchResult(BaseModel):
    jobs_retrieved: int
    listings: list[JobListing]
    warnings: list[str] = Field(default_factory=list)


class UploadResult(BaseModel):
    upload_id: str
    filename: str
    extension: str
    text: str


class ExportRequest(BaseModel):
    upload_id: str
    text: str
    as_format: str | None = None


class PdfWordBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float
    oy: float = 0.0
    text: str
    size: float = 0.0
    font: str = ""


class PdfPageBoxes(BaseModel):
    page: int
    width: float
    height: float
    words: list[PdfWordBox] = Field(default_factory=list)


class PdfPositionsResult(BaseModel):
    upload_id: str
    extension: str
    editable: bool
    pages: list[PdfPageBoxes] = Field(default_factory=list)


# LLM-internal schemas (not returned to users but used during extraction).
class LLMJobFit(BaseModel):
    fit_score: float = Field(ge=0, le=100)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    overqualified: bool = False
    reasoning: str = ""
    improvement: JobImprovement = Field(default_factory=JobImprovement)


AgentMessageRole = Literal["user", "assistant", "tool"]
