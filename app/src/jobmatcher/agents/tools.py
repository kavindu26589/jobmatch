"""ReAct tools exposed to the LLM agent, sharing the pipeline components.

Handlers write results into ``ctx.session`` (a persistent dict the agent graph
carries across nodes) and return JSON-serializable summaries for the model.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from gateway.protocols import ToolSpec

from ..domain.models import MatchRequest
from ..resume.keywords import detect_skills
from ..resume.parsers import extract_text

logger = logging.getLogger("jobmatcher.agent")

# async (ctx, args) -> JSON-serializable result dict
ToolHandler = Callable[..., Coroutine[Any, Any, dict[str, Any]]]

SEARCH_JOBS = ToolSpec(
    name="search_jobs",
    description=(
        "Search live internet job boards (remotive, greenhouse, lever, usajobs) for openings."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "free-text search keywords, e.g. 'backend engineer python'",
            },
            "location": {"type": "string", "description": "preferred location or 'Remote'"},
            "remote_only": {"type": "boolean", "description": "restrict to fully remote roles"},
            "limit": {
                "type": "integer",
                "description": "max listings to fetch",
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": ["query"],
    },
)

ANALYZE_RESUME = ToolSpec(
    name="analyze_resume",
    description="Parse a resume file (pdf/docx/txt/md) into a structured candidate profile.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "filesystem path to the resume file"}
        },
        "required": ["path"],
    },
)

ANALYZE_FIT = ToolSpec(
    name="analyze_fit",
    description="Score the candidate profile against the currently fetched jobs.",
    parameters={
        "type": "object",
        "properties": {
            "num_jobs": {
                "type": "integer",
                "description": "how many top jobs to score",
                "minimum": 1,
                "maximum": 20,
            }
        },
        "required": [],
    },
)

IMPROVE_RESUME = ToolSpec(
    name="improve_resume",
    description="Produce a resume improvement report against the currently scored top jobs.",
    parameters={
        "type": "object",
        "properties": {
            "num_targets": {
                "type": "integer",
                "description": "target jobs to optimize against",
                "minimum": 1,
                "maximum": 5,
            }
        },
        "required": [],
    },
)

AGENT_TOOLS: list[ToolSpec] = [SEARCH_JOBS, ANALYZE_RESUME, ANALYZE_FIT, IMPROVE_RESUME]


async def search_jobs_handler(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    listings, warnings = await ctx.search_jobs(
        MatchRequest(
            query=args.get("query", ""),
            location=args.get("location", ""),
            remote_only=bool(args.get("remote_only")),
            limit=int(args.get("limit") or 20),
        )
    )
    ctx.session["listings"] = listings
    ctx.session.setdefault("warnings", []).extend(warnings)
    return {
        "found": len(listings),
        "listings": [
            {
                "title": item.title,
                "company": item.company,
                "location": item.location,
                "url": item.url,
            }
            for item in listings[:15]
        ],
    }


async def analyze_resume_handler(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    path = args.get("path", "")
    if not path:
        return {"error": "no resume path provided"}
    try:
        text = extract_text(path)
    except Exception as exc:
        return {"error": f"could not read resume: {exc}"}
    profile, warnings = await ctx.extractor().extract(text)
    ctx.session["profile"] = profile
    ctx.session.setdefault("warnings", []).extend(warnings)
    return {
        "name": profile.contact.name,
        "years_experience": profile.years_experience,
        "target_titles": profile.target_titles,
        "skills": sorted(profile.all_skills())[:25],
        "summary": profile.summary[:300],
    }


async def analyze_fit_handler(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    profile = ctx.session.get("profile")
    listings = ctx.session.get("listings") or []
    if profile is None:
        return {"error": "no candidate profile yet; call analyze_resume first"}
    if not listings:
        return {"error": "no jobs fetched yet; call search_jobs first"}
    matches = await ctx.scorer().rank(
        profile, listings, llm_top_n=int(args.get("num_jobs") or 5), min_score=20.0
    )
    ctx.session["matches"] = matches
    return {
        "top_matches": [
            {
                "title": match.listing.title,
                "company": match.listing.company,
                "fit_score": match.score.fit_score,
                "missing_skills": match.score.missing_skills[:8],
            }
            for match in matches[:8]
        ]
    }


async def improve_resume_handler(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    profile = ctx.session.get("profile")
    matches = ctx.session.get("matches") or []
    if profile is None:
        return {"error": "no candidate profile yet; call analyze_resume first"}
    targets = [match.listing for match in matches]
    if not targets:
        return {"error": "no scored jobs yet; call search_jobs and analyze_fit first"}
    report = await ctx.improver().improve(profile, targets, n=int(args.get("num_targets") or 3))
    ctx.session["report"] = report
    return {
        "ats_score": report.overall_ats_score,
        "summary": report.summary[:300],
        "missing_keywords": [kw.keyword for kw in report.missing_keywords][:12],
        "priority_actions": [f"{a.priority} {a.action}" for a in report.priority_actions][:8],
    }


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "search_jobs": search_jobs_handler,
    "analyze_resume": analyze_resume_handler,
    "analyze_fit": analyze_fit_handler,
    "improve_resume": improve_resume_handler,
}


def skills_preview(ctx: Any) -> dict[str, Any]:
    profile = ctx.session.get("profile")
    if profile is None:
        return {}
    return {
        "skills": sorted(profile.all_skills()),
        "detected_from_resume": detect_skills(profile.raw_text or "")[:20],
    }
