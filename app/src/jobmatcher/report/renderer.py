"""Human- and machine-readable reporting for match results."""

from __future__ import annotations

import json
from pathlib import Path

from ..domain.models import MatchResult

_EMOJI = {">=80": ":green_circle:", ">=60": ":yellow_circle:", "default": ":red_circle:"}


def _score_badge(score: float) -> str:
    if score >= 80:
        return _EMOJI[">=80"]
    if score >= 60:
        return _EMOJI[">=60"]
    return _EMOJI["default"]


def render_matches(result: MatchResult) -> str:
    """A compact markdown table of ranked matches."""
    lines = [
        "## Top matches",
        "",
        "| # | Fit | Title | Company | Location | Missing skills |",
        "|---|----:|-------|---------|----------|----------------|",
    ]
    for match in result.matches[:10]:
        missing = ", ".join(match.score.missing_skills[:6]) or "—"
        lines.append(
            f"| {match.rank or '?'} | {_score_badge(match.score.fit_score)} "
            f"{match.score.fit_score:.0f} | "
            f"{match.listing.title} | {match.listing.company} | "
            f"{match.listing.location or '—'} | {missing} |"
        )
    if not result.matches:
        lines.append("_No matches above the minimum score._")
    if result.warnings:
        lines.append("")
        lines.append("## Warnings")
        for warning in result.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def render_improvement(result: MatchResult) -> str:
    report = result.improvement
    if report is None:
        return "_No improvement report produced._"
    lines = [
        "## Resume improvement",
        "",
        f"- **ATS score:** {report.overall_ats_score}/100",
        f"- **Target titles:** {', '.join(report.target_titles) or '—'}",
        "",
        report.summary,
        "",
        "### Missing keywords",
    ]
    if report.missing_keywords:
        lines.append("| Keyword | Appears in targets | Importance |")
        lines.append("|---------|-------------------:|------------|")
        for keyword in report.missing_keywords:
            lines.append(
                f"| {keyword.keyword} | {keyword.appears_in_targets} | {keyword.importance.value} |"
            )
    else:
        lines.append("_None detected — strong keyword coverage._")
    lines.append("")
    lines.append("### Priority actions")
    for action in report.priority_actions:
        lines.append(f"- **[{action.priority.value}]** {action.action}")
    for section in report.sections:
        lines.append("")
        lines.append(f"### {section.section.title()}")
        for strength in section.strengths:
            lines.append(f"- Strengths: {strength}")
        for issue in section.issues:
            lines.append(f"- Issue: {issue}")
        for suggestion in section.suggestions:
            lines.append(f"  - Rewrite: _{suggestion.rewritten}_ ({suggestion.rationale})")
    return "\n".join(lines)


def render_report(result: MatchResult) -> str:
    """The full human-readable report."""
    parts = [
        "# Job match report",
        f"_Generated {result.generated_at.isoformat()}_",
        f"- Jobs retrieved: {result.jobs_retrieved}",
        f"- Total LLM cost: **${result.total_cost_usd:.4f}**",
        "",
    ]
    if result.profile is not None:
        contact = result.profile.contact
        name = contact.name or "Candidate"
        parts.append(f"**Profile:** {name} · {contact.email or ''} · {contact.location or ''}")
        if result.profile.summary:
            parts.append(result.profile.summary)
        parts.append("")
    parts.append(render_matches(result))
    parts.append("")
    parts.append(render_improvement(result))
    if result.agent_transcript:
        parts.append("")
        parts.append("## Agent transcript")
        for message in result.agent_transcript:
            role = message.get("role", "step")
            content = (message.get("content") or "")[:400]
            parts.append(f"- **{role}:** {content}")
    return "\n".join(parts)


def save_report(result: MatchResult, directory: str | Path = "reports") -> tuple[Path, Path]:
    """Persist the report as Markdown and JSON; returns the two paths."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = result.generated_at.strftime("%Y%m%d-%H%M%S")
    md_path = directory / f"job-report-{stamp}.md"
    json_path = directory / f"job-report-{stamp}.json"
    md_path.write_text(render_report(result), encoding="utf-8")
    json_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return md_path, json_path
