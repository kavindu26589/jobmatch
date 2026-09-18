"""LLM-driven resume -> structured profile extraction with a safe fallback."""

from __future__ import annotations

import re

from gateway import LLMGateway
from gateway.errors import GatewayError
from pydantic import Field

from ..domain.models import ContactInfo, ResumeProfile
from .keywords import detect_skills, estimate_years_experience

_MAX_RESUME_CHARS = 40_000

RESUME_PARSING_SYSTEM = """You are an expert ATS resume parser and career analyst.

Extract the candidate profile from the resume text into the required JSON schema
(emit_json). Rules:
- hard_skills: concrete technical capabilities (languages, frameworks, tools, platforms).
- soft_skills: collaboration, leadership, and communication strengths.
- target_titles: 2-6 realistic job titles this profile is best suited for.
- years_experience: best estimate in years (fractional ok); null when unknown.
- summary: a fresh 1-3 sentence positioning statement, never a verbatim copy.
- Do not invent facts. Return empty lists for anything not present."""


class ResumeProfileStructured(ResumeProfile):
    """ResumeProfile without the raw transcript (kept out of the model schema)."""

    raw_text: str | None = Field(default=None, exclude=True)  # type: ignore[assignment]  # intentional: schema-only model widens the base field


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[ .\-]?)?(?:\(\d{2,4}\)|\d{2,4})[ .\-]?\d{3,4}[ .\-]?\d{3,4}")
_LINKEDIN_RE = re.compile(r"linkedin\.com/in/[\w-]+", re.IGNORECASE)
_GITHUB_RE = re.compile(r"github\.com/[\w-]+", re.IGNORECASE)

_NAME_HEADER_WORDS = frozenset(
    {
        "summary",
        "profile",
        "objective",
        "experience",
        "education",
        "skills",
        "projects",
        "certifications",
        "certificate",
        "certificates",
        "achievements",
        "accomplishments",
        "additional",
        "contact",
        "information",
        "references",
        "qualifications",
        "activities",
        "leadership",
        "awards",
        "honors",
        "languages",
        "interests",
    }
)


def _extract_name(text: str) -> str | None:
    """Best-effort name from an all-caps header line near the top of a resume.

    Runs only in the heuristic fallback path; the LLM extraction names the
    candidate precisely. Multi-word all-caps lines that are actually section
    headers (or stacked job titles) are filtered via ``_NAME_HEADER_WORDS``.
    """
    for line in text.splitlines()[:12]:
        line = line.strip()
        if not line or len(line) > 80:
            continue
        words = re.findall(r"[A-Za-z]+", line)
        caps = [
            word
            for word in words
            if len(word) >= 3 and word.isupper() and word.lower() not in _NAME_HEADER_WORDS
        ]
        if len(caps) >= 2 and any(len(c) >= 4 for c in caps):
            return " ".join(caps)
    return None


def extract_contact(text: str) -> ContactInfo:
    email_match = _EMAIL_RE.search(text)
    phone_match = _PHONE_RE.search(text[:2000])
    linkedin_match = _LINKEDIN_RE.search(text)
    github_match = _GITHUB_RE.search(text)
    return ContactInfo(
        name=_extract_name(text),
        email=email_match.group(0) if email_match else None,
        phone=phone_match.group(0).strip() if phone_match else None,
        linkedin=linkedin_match.group(0) if linkedin_match else None,
        github=github_match.group(0) if github_match else None,
    )


class ResumeExtractor:
    """Structurally parses resume text into a :class:`ResumeProfile`."""

    def __init__(self, gateway: LLMGateway, provider: str, model: str) -> None:
        self.gateway = gateway
        self.provider = provider
        self.model = model

    async def extract(self, resume_text: str) -> tuple[ResumeProfile, list[str]]:
        warnings: list[str] = []
        if not resume_text.strip():
            raise ValueError("resume text is empty")
        try:
            structured_profile = await self.gateway.structured(
                self.provider,
                self.model,
                schema=ResumeProfileStructured,
                system=RESUME_PARSING_SYSTEM,
                user=resume_text[:_MAX_RESUME_CHARS],
            )
            profile: ResumeProfile = structured_profile.model_copy(update={"raw_text": resume_text})
            if profile.years_experience is None:
                profile.years_experience = estimate_years_experience(profile)
            detected = detect_skills(resume_text, excludes=profile.all_skills())
            if detected:
                profile.hard_skills.extend(
                    skill for skill in detected if skill not in profile.all_skills()
                )
        except GatewayError as exc:
            warnings.append(
                f"LLM extraction failed ({type(exc).__name__}); used heuristic fallback"
            )
            profile = self.fallback(resume_text)
        return profile, warnings

    def fallback(self, resume_text: str) -> ResumeProfile:
        profile = ResumeProfile(
            contact=extract_contact(resume_text),
            hard_skills=detect_skills(resume_text),
            soft_skills=[],
            raw_text=resume_text,
        )
        profile.years_experience = estimate_years_experience(profile)
        return profile
