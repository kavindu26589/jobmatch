"""Resume text extraction: PDF, DOCX, plain text, and markdown."""

from __future__ import annotations

import re
from pathlib import Path

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md", ".rtf"})


class UnsupportedFormatError(ValueError):
    pass


class EmptyResumeError(ValueError):
    pass


def fold_whitespace(text: str) -> str:
    return re.sub(r"[ \t\u00a0]+", " ", text)


_SINGLE_LETTER_RE = re.compile(r"\b([A-Za-z0-9])[ \t](?=[A-Za-z0-9]\b)")
_SYMBOL_SPACING_RE = re.compile(r"([A-Za-z0-9])[ \t\u00a0]+([@.])[ \t\u00a0]+([A-Za-z0-9])")


def collapse_letter_spacing(text: str) -> str:
    """Undo the "P y t h o n" letter-spacing artifact common in designed PDFs.

    pypdf often emits glyphs separated so that each character reads as a
    standalone word ("S U M M A R Y"), which defeats keyword matching, section
    splitting, and contact extraction. These fonts also separate *words* with a
    look of double spaces, so this joins exactly **one** whitespace char between
    two single characters (letters read singly inside a word), then folds the
    leftover whitespace runs back to a single space (word boundaries). Ordinary
    prose is effectively untouched: two multi-letter words never merge, and a
    lone single-letter word only joins when the next token is a single letter
    too (so "a solid" may become "asolid", but "I am", "node js" survive).
    Email-like lines (those containing ``@``) additionally collapse spacing
    around ``.`` and ``@`` so "j a n e @ g m a i l . c o m" round-trips.
    """
    text = _SINGLE_LETTER_RE.sub(r"\1", text)
    text = fold_whitespace(text)
    if "@" in text:
        text = "\n".join(
            _SYMBOL_SPACING_RE.sub(r"\1\2\3", line) if "@" in line else line
            for line in text.splitlines()
        )
    return text


def extract_text(path: str | Path) -> str:
    """Extract raw text from a resume file, dispatching on extension."""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"resume file not found: {target}")
    suffix = target.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"unsupported resume format '{suffix or '(none)'}' "
            f"(supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))})"
        )
    if suffix == ".pdf":
        text = collapse_letter_spacing(_extract_pdf(target))
    elif suffix == ".docx":
        text = collapse_letter_spacing(_extract_docx(target))
    else:
        text = fold_whitespace(target.read_text(encoding="utf-8", errors="replace"))
    text = "\n".join(line.rstrip() for line in text.splitlines())
    if not text.strip():
        raise EmptyResumeError(f"resume file is empty or unreadable: {target}")
    return text


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFormatError(
            "pypdf is required for PDF parsing (pip install pypdf)"
        ) from exc

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFormatError(
            "python-docx is required for DOCX parsing (pip install python-docx)"
        ) from exc

    document = Document(str(path))
    lines: list[str] = []
    for paragraph in document.paragraphs:
        if paragraph.text:
            lines.append(fold_whitespace(paragraph.text))
    for table in document.tables:
        for row in table.rows:
            cells = [fold_whitespace(cell.text) for cell in row.cells if cell.text]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


_SECTION_HEADERS: dict[str, tuple[str, ...]] = {
    "summary": (
        "professional summary",
        "professional profile",
        "summary",
        "profile",
        "about me",
        "objective",
        "career objective",
    ),
    "skills": (
        "technical skills",
        "core competencies",
        "skills",
        "technologies",
        "tools & technologies",
        "tools and technologies",
        "proficiencies",
        "areas of expertise",
        "expertise",
    ),
    "experience": (
        "professional experience",
        "work experience",
        "work history",
        "employment history",
        "experience",
        "professional history",
        "career history",
    ),
    "education": ("education", "academic background", "academics", "education & training"),
    "projects": (
        "projects",
        "personal projects",
        "side projects",
        "project experience",
        "open source",
        "select projects",
    ),
    "certifications": (
        "certifications",
        "certificates",
        "licenses",
        "credentials",
        "certification",
    ),
    "achievements": ("achievements", "awards", "honors", "publications", "patents"),
    "additional": (
        "additional information",
        "additional",
        "languages",
        "volunteering",
        "interests",
        "extracurricular",
        "talks & mentorships",
    ),
}

_SECTION_PATTERN = re.compile(
    r"^(?P<header>"
    + "|".join(
        re.sub(r"[^a-z0-9&]+", r"[^a-z0-9&\n]*", header.replace("&", "&")) + r"$"
        for header in sum(_SECTION_HEADERS.values(), ())
    )
    + r")$",
    re.IGNORECASE,
)


def split_sections(text: str) -> dict[str, str]:
    """Heuristically split raw resume text into named sections.

    Lines matching a known header (case-insensitive) start a new section.
    Unmatched leading text lands under ``"header"``.
    """
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in text.splitlines():
        stripped = line.strip()
        header = _match_header(stripped)
        if header is not None:
            current = header
            sections.setdefault(current, [])
        else:
            sections[current].append(stripped)
    return {name: "\n".join(filter(None, lines)).strip() for name, lines in sections.items()}


def _match_header(line: str) -> str | None:
    if not line or len(line) > 50:
        return None
    if not _SECTION_PATTERN.fullmatch(line):
        return None
    lowered = line.lower()
    for name, aliases in sorted(_SECTION_HEADERS.items(), key=lambda kv: -max(map(len, kv[1]))):
        if lowered in aliases or lowered.rstrip(":") in aliases:
            return name
    return None
