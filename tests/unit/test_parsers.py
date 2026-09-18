"""Tests for resume text parsing helpers."""

from __future__ import annotations

from jobmatcher.resume.parsers import (
    collapse_letter_spacing,
    extract_text,
    split_sections,
)


def test_extract_text_reads_txt(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text("line one\nline two\n", encoding="utf-8")
    assert extract_text(str(path)) == "line one\nline two"


def test_collapse_letter_spacing_joins_infographic_words():
    spaced = "P y t h o n   a n d   R e a c t\nS U M M A R Y"
    assert collapse_letter_spacing(spaced) == "Python and React\nSUMMARY"


def test_collapse_letter_spacing_keeps_normal_prose():
    prose = "node js and React Native (I am a dev)"
    assert collapse_letter_spacing(prose) == prose


def test_collapse_letter_spacing_recovers_email():
    spaced = "J a n e   D o e\njane . doe @ gmail . com"
    result = collapse_letter_spacing(spaced)
    assert "jane.doe@gmail.com" in result
    assert result.startswith("Jane Doe")


def test_collapse_letter_spacing_makes_sections_detectable():
    spaced = "S U M M A R Y\nPython developer.\nE D U C A T I O N\nB.Sc."
    sections = split_sections(collapse_letter_spacing(spaced))
    assert {"summary", "education"} <= set(sections)


def test_extract_text_unsupported_extension(tmp_path):
    path = tmp_path / "resume.bin"
    path.write_bytes(b"\x00\x01")
    try:
        extract_text(str(path))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unsupported extension")


def test_extract_text_missing_file():
    try:
        extract_text("C:/definitely/not/a/file.pdf")
    except (ValueError, OSError):
        pass
    else:
        raise AssertionError("expected an error for a missing file")
