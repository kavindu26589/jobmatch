"""In-place patching of uploaded PDF/DOCX files so edits keep the original design.

Extraction of text from a designed resume is lossy: re-generating the file from
text (the historical fallback) throws away layout, icons and fonts. Instead, this
module locates the *changed* phrases (whitespace/folding-insensitive) inside the
original file and rewrites them at their original positions:

- PDF -> a plain proportional font auto-shrunk to fit the original box, with the
  surrounding graphic content preserved (text-only redaction).
- DOCX -> the paragraph runs are rewritten, keeping their existing formatting.

Anything that cannot be located is skipped and reported in ``notes`` so the
caller can fall back (or tell the user).
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"\S+|\s+")


@dataclass(frozen=True)
class WordBox:
    """Editable word segment on a PDF page, in page coordinates."""

    x0: float
    y0: float
    x1: float
    y1: float
    oy: float
    text: str
    size: float
    font: str


@dataclass(frozen=True)
class PageBoxes:
    page: int
    width: float
    height: float
    words: list[WordBox] = field(default_factory=list)


@dataclass
class Change:
    """A single edited phrase: what the file used to say vs. now."""

    original: str
    rewritten: str


@dataclass
class PatchResult:
    data: bytes
    applied: int
    total: int
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Hunk:
    orig_start: int
    orig_end: int
    new_start: int
    new_end: int


def diff_texts(before: str, after: str) -> list[Change]:
    """Word-level diff producing ``(original -> rewritten)`` hunks.

    Hunks that are adjacent in the *same line* (gap of a single separator and
    no newline between them) are merged, so a rewrite touching consecutive
    words becomes one positioned replacement instead of several overlapping
    ones. Whitespace-only hunks (pure insertions/deletions of separators) are
    dropped, as they cannot be positioned on a page. Merging never crosses a
    line break, keeping each hunk inside one DOCX paragraph.
    """
    if before == after:
        return []
    tokens_b = _TOKEN_RE.findall(before)
    tokens_a = _TOKEN_RE.findall(after)
    n, m = len(tokens_b), len(tokens_a)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = (
                dp[i + 1][j + 1] + 1
                if tokens_b[i] == tokens_a[j]
                else max(dp[i + 1][j], dp[i][j + 1])
            )
    hunks: list[_Hunk] = []
    i = j = 0
    while i < n and j < m:
        if tokens_b[i] == tokens_a[j]:
            i += 1
            j += 1
            continue
        os, ns = i, j
        while i < n and j < m and tokens_b[i] != tokens_a[j]:
            i += 1
            j += 1
        while i < n and (j == m or tokens_b[i] != tokens_a[j]):
            i += 1
        while j < m and (i == n or tokens_b[i] != tokens_a[j]):
            j += 1
        hunks.append(_span(before, after, tokens_b, tokens_a, os, ns, i, j))
    if i < n or j < m:  # trailing deletions / insertions
        hunks.append(_span(before, after, tokens_b, tokens_a, i, j, n, m))
    return _merge_hunks(before, after, hunks)


def _span(
    before: str,
    after: str,
    tokens_b: list[str],
    tokens_a: list[str],
    i0: int,
    j0: int,
    i1: int,
    j1: int,
) -> _Hunk:
    def offset(tokens: list[str], index: int) -> int:
        return sum(len(t) for t in tokens[:index])

    return _Hunk(
        orig_start=offset(tokens_b, i0),
        orig_end=offset(tokens_b, i1),
        new_start=offset(tokens_a, j0),
        new_end=offset(tokens_a, j1),
    )


def _merge_hunks(before: str, after: str, hunks: list[_Hunk]) -> list[Change]:
    changes: list[Change] = []
    group: _Hunk | None = None
    for hunk in hunks:
        if group is None:
            group = hunk
            continue
        between = before[group.orig_end : hunk.orig_start]
        if "\n" not in between and len(between) <= 2:
            group = _Hunk(
                orig_start=group.orig_start,
                orig_end=hunk.orig_end,
                new_start=group.new_start,
                new_end=hunk.new_end,
            )
            continue
        _flush(group, before, after, changes)
        group = hunk
    if group is not None:
        _flush(group, before, after, changes)
    return changes


def _flush(group: _Hunk, before: str, after: str, changes: list[Change]) -> None:
    original = before[group.orig_start : group.orig_end]
    rewritten = after[group.new_start : group.new_end]
    if original.strip():
        changes.append(Change(original=original, rewritten=rewritten))


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


@dataclass
class _Char:
    c: str
    x0: float
    y0: float
    x1: float
    y1: float
    oy: float
    font: str
    size: float


def _import_pymupdf() -> Any:
    try:  # PyMuPDF >= 1.24 ships the `pymupdf` import name
        import pymupdf
    except ImportError:  # pragma: no cover - older releases
        import fitz as pymupdf  # type: ignore[import-untyped, no-redef]
    return pymupdf


def _page_chars(page: Any) -> list[_Char]:
    chars: list[_Char] = []
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for glyph in span.get("chars", []):
                    x0, y0, x1, y1 = glyph["bbox"]
                    chars.append(
                        _Char(
                            c=glyph["c"],
                            x0=x0,
                            y0=y0,
                            x1=x1,
                            y1=y1,
                            oy=glyph["origin"][1],
                            font=span.get("font", ""),
                            size=float(span.get("size", 0.0)),
                        )
                    )
    return chars


def extract_word_boxes(path: str | Path) -> list[PageBoxes]:
    """Per-page editable word boxes for the UI overlay (``/positions``)."""
    fitz = _import_pymupdf()
    pages: list[PageBoxes] = []
    with fitz.open(str(path)) as doc:
        for number, page in enumerate(doc, start=1):
            rect = page.rect
            # ``get_text("words")`` reconstructs words from the text layer, which
            # correctly segments even letter-spaced infographic fonts (the glyph
            # bbox gaps are uniform there, so geometry-based clustering fails).
            words = [
                WordBox(
                    x0=x0,
                    y0=y0,
                    x1=x1,
                    y1=y1,
                    oy=y0,
                    text=word,
                    size=0.0,
                    font="",
                )
                for x0, y0, x1, y1, word, _block, _line, _wno in page.get_text("words")
            ]
            pages.append(
                PageBoxes(
                    page=number,
                    width=round(rect.width, 2),
                    height=round(rect.height, 2),
                    words=words,
                )
            )
    return pages


@dataclass
class _Located:
    box: tuple[float, float, float, float]
    size: float
    baseline: float


def _locate(page_chars: list[_Char], phrase: str) -> _Located | None:
    """Find ``phrase`` (whitespace-folded, case-insensitive) in the page glyphs."""
    target = _WS_RE.sub("", phrase)
    if not target:
        return None
    stream = _WS_RE.sub("", "".join(ch.c for ch in page_chars))
    start = stream.find(target)
    if start == -1:
        return None
    count = 0
    begin = end = 0
    for idx, ch in enumerate(page_chars):
        if ch.c == " ":
            continue
        if count == start:
            begin = idx
        count += 1
        if count == start + len(target):
            end = idx + 1
            break
    match = page_chars[begin:end]
    return _Located(
        box=(
            min(ch.x0 for ch in match),
            min(ch.y0 for ch in match),
            max(ch.x1 for ch in match),
            max(ch.y1 for ch in match),
        ),
        size=max(ch.size for ch in match),
        baseline=max(ch.oy for ch in match),
    )


@dataclass(frozen=True)
class _PdfPlan:
    """Dry-run location for one PDF change: binds a phrase to a glyph box."""

    change: Change
    placeable: bool
    page: int | None = None
    box: tuple[float, float, float, float] | None = None
    size: float | None = None
    baseline: float | None = None


def _plan_pdf(data: bytes, changes: list[Change]) -> list[_PdfPlan]:
    """Deterministic dry-run: locate every change *without* mutating bytes.

    Identical phrases bind to *distinct* glyph boxes by consuming glyphs as
    ``_patch_pdf`` does, so the Nth approved occurrence binds to exactly the
    page/box that was previewed.
    """
    fitz = _import_pymupdf()
    doc = fitz.open(stream=data, filetype="pdf")
    plans: list[_PdfPlan] = []
    try:
        # Per-page mutable glyph lists consumed in document order, exactly the
        # traversal ``_patch_pdf`` uses to redact + rewrite.
        pages: list[list[_Char]] = [_page_chars(page) for page in doc]
        for change in changes:
            located = None
            found_page: int | None = None
            for page_index, page_chars in enumerate(pages):
                match = _locate(page_chars, change.original)
                if match is None:
                    continue
                # Redaction also erases the 0.15*size pad we add in _patch_pdf,
                # so consume those glyphs too -> repeated phrases stay distinct.
                pad = 0.15 * match.size
                x0, y0, x1, y1 = match.box
                pages[page_index] = [
                    ch
                    for ch in page_chars
                    if not (
                        ch.x1 >= x0 - pad
                        and ch.x0 <= x1 + pad
                        and ch.y1 >= y0 - pad
                        and ch.y0 <= y1 + pad
                    )
                ]
                located = match
                found_page = page_index
                break
            if located is None or found_page is None:
                plans.append(_PdfPlan(change=change, placeable=False))
                continue
            plans.append(
                _PdfPlan(
                    change=change,
                    placeable=True,
                    page=found_page,
                    box=located.box,
                    size=located.size,
                    baseline=located.baseline,
                )
            )
    finally:
        doc.close()
    return plans


def _patch_pdf(
    data: bytes,
    changes: list[Change],
    *,
    approve: set[int] | None = None,
) -> PatchResult:
    fitz = _import_pymupdf()
    plans = _plan_pdf(data, changes)
    doc = fitz.open(stream=data, filetype="pdf")
    notes: list[str] = []
    applied = 0
    try:
        for index, plan in enumerate(plans):
            if approve is not None and index not in approve:
                notes.append(f"skipped: {plan.change.original[:40]!r}")
                continue
            if (
                not plan.placeable
                or plan.page is None
                or plan.box is None
                or plan.size is None
                or plan.baseline is None
            ):
                if not plan.placeable:
                    notes.append(f"could not place: {plan.change.original[:40]!r}")
                continue
            page = doc[plan.page]
            x0, y0, x1, y1 = plan.box
            pad = 0.15 * plan.size
            rect = fitz.Rect(max(0.0, x0 - pad), max(0.0, y0 - pad), x1 + pad, y1 + pad)
            page.add_redact_annot(rect)
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
            )
            if plan.change.rewritten.strip():
                fontsize = plan.size
                width1 = fitz.get_text_length(plan.change.rewritten, fontname="helv", fontsize=1)
                if width1 > 0:
                    fontsize = min(fontsize, (x1 - x0) / width1)
                height_cap = (y1 - y0) * 1.25
                fontsize = max(4.0, min(fontsize, height_cap))
                try:
                    page.insert_text(
                        (x0, plan.baseline + 0.2 * fontsize),
                        plan.change.rewritten,
                        fontsize=fontsize,
                        fontname="helv",
                    )
                except Exception:  # pragma: no cover - font/glyph edge cases
                    notes.append(f"could not write: {plan.change.rewritten[:40]!r}")
                    continue
            applied += 1
        data = doc.tobytes()
        if applied == 0 and changes:
            notes.insert(0, "no changes were placed on the PDF")
    finally:
        doc.close()
    return PatchResult(data=data, applied=applied, total=len(changes), notes=notes)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _iter_paragraphs(document: Any) -> Iterator[Any]:
    yield from document.paragraphs
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_paragraphs(cell)


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    parts = re.split(r"(\s+)", re.sub(r"\s+", " ", phrase.strip()))
    pattern = "".join(r"\\s+" if part.isspace() else re.escape(part) for part in parts)
    return re.compile(pattern, re.IGNORECASE)


def _replace_in_paragraph(paragraph: Any, pattern: re.Pattern[str], replacement: str) -> bool:
    """Rewrite the first ``pattern`` match in a paragraph across its runs.

    The replacement inherits the formatting of the run where the match starts;
    runs fully inside the match are emptied.
    """
    full = paragraph.text
    match = pattern.search(full)
    if not match:
        return False
    start, end = match.span()
    runs = paragraph.runs
    if not runs:
        return False
    cum: list[int] = []
    total = 0
    for run in runs:
        total += len(run.text)
        cum.append(total)
    if end > total:  # pragma: no cover - defensive
        return False

    def run_index(offset: int) -> int:
        for idx, boundary in enumerate(cum):
            if offset < boundary:
                return idx
        return len(runs) - 1

    i0 = run_index(start)
    i1 = run_index(end - 1)
    off0 = cum[i0 - 1] if i0 > 0 else 0
    off1 = cum[i1 - 1] if i1 > 0 else 0
    prefix = runs[i0].text[: start - off0]
    if i0 == i1:
        tail = runs[i0].text[end - off0 :]
        runs[i0].text = prefix + replacement + tail
    else:
        tail = runs[i1].text[end - off1 :]
        runs[i0].text = prefix + replacement
        for run in runs[i0 + 1 : i1 + 1]:
            run.text = ""
        runs[i1].text = tail
    return True


def _patch_docx(
    data: bytes,
    changes: list[Change],
    *,
    approve: set[int] | None = None,
) -> PatchResult:
    from docx import Document

    document = Document(io.BytesIO(data))
    notes: list[str] = []
    applied = 0
    for index, change in enumerate(changes):
        if approve is not None and index not in approve:
            notes.append(f"skipped: {change.original[:40]!r}")
            continue
        pattern = _phrase_pattern(change.original)
        placed = any(
            _replace_in_paragraph(paragraph, pattern, change.rewritten)
            for paragraph in _iter_paragraphs(document)
        )
        if placed:
            applied += 1
        else:
            notes.append(f"could not place: {change.original[:40]!r}")
    buffer = io.BytesIO()
    document.save(buffer)
    return PatchResult(data=buffer.getvalue(), applied=applied, total=len(changes), notes=notes)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def patch_binary(
    data: bytes,
    original_text: str,
    edited_text: str,
    kind: Literal["pdf", "docx"],
) -> PatchResult:
    changes = diff_texts(original_text, edited_text)
    if not changes:
        return PatchResult(data=data, applied=0, total=0)
    try:
        from .metrics import maybe_apply_metrics

        maybe_apply_metrics(data, changes, kind)
    except Exception:
        pass
    if kind == "pdf":
        return _patch_pdf(data, changes)
    return _patch_docx(data, changes)


@dataclass(frozen=True)
class PreviewTarget:
    """A single located (but *not* yet mutated) change, ready for human review.

    ``occurrence`` is the 0-based index of ``original`` among the identical
    phrases on the document (0, 1, 2… for repeated occurrences). Preview and
    apply derive it with the *same* deterministic traversal, so the Nth
    approved occurrence binds to exactly the ``page``/``box`` that was
    previewed — no re-locating onto a different, phrase-identical spot.
    """

    change: Change
    occurrence: int
    placeable: bool
    page: int | None = None
    box: tuple[float, float, float, float] | None = None
    size: float | None = None
    baseline: float | None = None
    note: str = ""


@dataclass(frozen=True)
class PreviewResult:
    """Dry-run outcome: nothing is mutated, every occurrence is located."""

    targets: list[PreviewTarget]
    total: int
    placeable: int


def _plan(
    data: bytes,
    changes: list[Change],
    kind: Literal["pdf", "docx"],
) -> tuple[list[PreviewTarget], int]:
    """Dry-run occurrence model shared by preview and apply.

    ``occurrence`` is the 0-based position in ``changes`` — the exact key
    ``apply_binary`` uses for approval — so the Nth approved occurrence binds
    to precisely the ``page``/``box`` shown in the preview. PDF uses the same
    consume-on-place traversal as ``_patch_pdf``; DOCX scans paragraphs in the
    same order as ``_patch_docx``. Nothing here mutates ``data``.
    """
    if kind == "pdf":
        plans = _plan_pdf(data, changes)
        targets = [
            PreviewTarget(
                change=plan.change,
                occurrence=index,
                placeable=plan.placeable,
                page=plan.page,
                box=plan.box,
                size=plan.size,
                baseline=plan.baseline,
                note="" if plan.placeable else f"could not place: {plan.change.original[:40]!r}",
            )
            for index, plan in enumerate(plans)
        ]
        return targets, sum(1 for plan in plans if plan.placeable)
    from docx import Document

    document = Document(io.BytesIO(data))
    targets = []
    placeable = 0
    for index, change in enumerate(changes):
        pattern = _phrase_pattern(change.original)
        found = any(pattern.search(paragraph.text) for paragraph in _iter_paragraphs(document))
        if found:
            placeable += 1
        targets.append(
            PreviewTarget(
                change=change,
                occurrence=index,
                placeable=found,
                note="" if found else f"could not place: {change.original[:40]!r}",
            )
        )
    return targets, placeable


def preview_binary(
    data: bytes,
    original_text: str,
    edited_text: str,
    kind: Literal["pdf", "docx"],
) -> PreviewResult:
    """Locate every change *without* altering the file (human-gate preview)."""
    changes = diff_texts(original_text, edited_text)
    targets, placeable = _plan(data, changes, kind)
    return PreviewResult(targets=targets, total=len(changes), placeable=placeable)


def apply_binary(
    data: bytes,
    original_text: str,
    edited_text: str,
    kind: Literal["pdf", "docx"],
    *,
    approve: set[int],
) -> PatchResult:
    """Apply **only** the human-approved occurrences (by preview index) in place.

    ``approve`` carries the occurrence indices returned by
    :func:`preview_binary`; every other change is left untouched. Changes that
    can no longer be located on the current bytes are skipped with a note
    rather than silently bound elsewhere.
    """
    changes = diff_texts(original_text, edited_text)
    if not changes:
        return PatchResult(data=data, applied=0, total=0)
    if kind == "pdf":
        return _patch_pdf(data, changes, approve=approve)
    return _patch_docx(data, changes, approve=approve)
