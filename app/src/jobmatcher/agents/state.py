"""Typed state shared by the LangGraph pipeline and the ReAct agent."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from ..domain.models import (
    JobListing,
    JobMatch,
    MatchRequest,
    MatchResult,
    ResumeImprovementReport,
    ResumeProfile,
)


class AgentState(TypedDict, total=False):
    """State flowing through the LangGraph nodes.

    Scalar channels are replaced on write; the annotated list channels append.
    """

    request: MatchRequest
    resume_text: str
    profile: ResumeProfile | None
    listings: list[JobListing]
    matches: list[JobMatch]
    report: ResumeImprovementReport | None
    result: MatchResult | None
    errors: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    messages: Annotated[list[dict[str, Any]], operator.add]
    steps: int
    final: bool
