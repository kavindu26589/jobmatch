"""Tests for resume extraction (contact regex + heuristic fallback)."""

from __future__ import annotations

import pytest
from tests.conftest import SAMPLE_RESUME, FakeGateway, sample_profile

from jobmatcher.resume.extractor import ResumeExtractor, extract_contact


def test_extract_contact_detects_email_phone_linkedin():
    contact = extract_contact(SAMPLE_RESUME)
    assert contact.email == "jane@example.com"
    assert contact.phone is not None
    assert contact.linkedin == "linkedin.com/in/janedoe"


def test_extract_contact_no_matches():
    contact = extract_contact("no contact details anywhere here")
    assert contact.email is None
    assert contact.phone is None


def test_extract_contact_name_from_caps_header():
    text = "JANE DOE\nSENIOR ENGINEER\njane@example.com"
    assert extract_contact(text).name == "JANE DOE"


def test_extract_contact_name_ignores_section_headers():
    text = "PROFESSIONAL SUMMARY\nPython developer.\nKAVINDU HANSAKA JAYASINGHE\n"
    assert extract_contact(text).name == "KAVINDU HANSAKA JAYASINGHE"


class _NoStructuredStub:
    """Never answers: proves the heuristic fallback needs no model."""

    async def structured(self, *a, **k):  # pragma: no cover - never reached
        raise AssertionError("fallback must not call the model")


def test_fallback_builds_profile_without_llm():
    extractor = ResumeExtractor(_NoStructuredStub(), "zen", "model")
    profile = extractor.fallback(SAMPLE_RESUME)
    assert "python" in profile.hard_skills
    assert profile.contact.email == "jane@example.com"


async def test_extract_uses_llm_when_available():
    fake = FakeGateway(structured={"ResumeProfileStructured": sample_profile()})
    extractor = ResumeExtractor(fake, "zen", "model")
    profile, warnings = await extractor.extract(SAMPLE_RESUME)
    assert profile.contact.name == "Jane Doe"
    assert not warnings
    assert fake.structured_calls


async def test_extract_falls_back_when_llm_raises():
    class ExplodingStub:
        async def structured(self, *a, **k):
            from gateway.errors import ServerError

            raise ServerError("boom")

    extractor = ResumeExtractor(ExplodingStub(), "zen", "model")
    profile, warnings = await extractor.extract(SAMPLE_RESUME)
    assert "python" in profile.hard_skills
    assert any("fallback" in warning for warning in warnings)
