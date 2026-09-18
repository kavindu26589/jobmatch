"""Tests for keyword detection and experience estimation."""

from __future__ import annotations

from jobmatcher.resume.keywords import (
    SKILL_LEXICON,
    detect_skills,
    estimate_years_experience,
    tokenize,
)


def test_tokenize_splits_on_punctuation():
    assert tokenize("Python, pandas & SQL!") == ["python", "pandas", "sql"]


def test_detect_skills_finds_known_lexicon():
    detected = detect_skills("Proficient with python, pandas, kubernetes and aws.")
    for skill in ("python", "pandas", "kubernetes", "aws"):
        assert skill in detected


def test_detect_skills_excludes_words():
    from tests.conftest import sample_profile

    profile = sample_profile()
    extra = detect_skills(SAMPLE_EXCLUDES, excludes=profile.all_skills())
    assert "python" not in extra


SAMPLE_EXCLUDES = "python sql aws"


def test_estimate_years_experience_from_dates():
    from tests.conftest import sample_profile

    profile = sample_profile(
        experience=[
            {"title": "A", "company": "X", "start_date": "2020-01", "end_date": "2023-06"},
        ]
    )
    years = estimate_years_experience(profile)
    assert years is not None and 3.0 <= years <= 4.0


def test_estimate_years_experience_unknown():
    assert estimate_years_experience(None) is None


def test_skill_lexicon_is_lowercase():
    for skill in SKILL_LEXICON:
        assert skill == skill.lower()
