"""Shared domain value types."""

from __future__ import annotations

from enum import StrEnum


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class Importance(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class MatchPhase(StrEnum):
    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    LLM = "llm"
    COMBINED = "combined"
