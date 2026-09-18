"""LangGraph orchestration.

Two compiled graphs share every domain component:

- ``build_pipeline`` — a linear DAG:
  load_resume -> extract_profile -> search_jobs -> score -> improve -> finalize.
- ``build_agent`` — a ReAct loop where the model chooses between the agent
  tools (search_jobs, analyze_resume, analyze_fit, improve_resume) and a
  natural-language answer, routed via conditional edges.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from gateway.protocols import Message, ToolCall
from langgraph.graph import END, START, StateGraph

from ..domain.models import MatchRequest, MatchResult
from ..resume.parsers import extract_text
from .state import AgentState
from .tools import AGENT_TOOLS, TOOL_HANDLERS

logger = logging.getLogger("jobmatcher.graph")

MAX_AGENT_STEPS = 8

AGENT_SYSTEM = """You are a job-matching copilot. Help the user discover jobs, understand how
they fit, and improve their resume.

You have tools. Use them in a sensible order:
1. analyze_resume — builds the candidate profile from their resume file.
2. search_jobs — fetches live openings from internet job boards.
3. analyze_fit — scores the profile against the currently fetched jobs.
4. improve_resume — produces a resume improvement plan against the top jobs.

Once you have the data needed, give a concise final answer: the strongest matches
(title, company, location, fit), the biggest skill gaps, and 2-4 concrete resume
improvements. Never invent jobs, companies, or skills. Use the tools' returned
data only."""


def _assemble_result(
    ctx: Any,
    state: AgentState,
    *,
    transcript: list[dict[str, Any]] | None = None,
) -> MatchResult:
    session = ctx.session
    merged_warnings: list[str] = []
    for warning in (
        state.get("warnings") or [],
        state.get("errors") or [],
        session.get("warnings") or [],
    ):
        merged_warnings.extend(str(item) for item in warning)
    deduped = list(dict.fromkeys(merged_warnings))
    return MatchResult(
        profile=session.get("profile") or state.get("profile"),
        jobs_retrieved=len(session.get("listings") or state.get("listings") or []),
        matches=session.get("matches") or state.get("matches") or [],
        improvement=session.get("report") or state.get("report"),
        warnings=deduped,
        usage=[record.as_dict() for record in ctx.gateway.usage_snapshot()],
        total_cost_usd=ctx.gateway.total_cost(),
        agent_transcript=transcript or [],
    )


def build_pipeline(ctx: Any) -> Any:
    """Deterministic pipeline graph: analyze -> search -> score -> improve."""

    graph = StateGraph(AgentState)

    async def load_resume(state: AgentState) -> dict[str, Any]:
        request = state.get("request") or MatchRequest()
        text = request.resume_text
        if request.resume_path:
            try:
                text = extract_text(request.resume_path)
            except Exception as exc:
                return {"errors": [f"could not read resume: {exc}"]}
        if not text or not text.strip():
            return {"errors": ["no resume text supplied (set resume_path or resume_text)"]}
        return {"resume_text": text}

    async def extract_profile(state: AgentState) -> dict[str, Any]:
        if state.get("errors"):
            return {}
        profile, warnings = await ctx.extractor().extract(state["resume_text"])
        return {"profile": profile, "warnings": warnings}

    async def search_jobs_node(state: AgentState) -> dict[str, Any]:
        if state.get("errors"):
            return {}
        listings, warnings = await ctx.search_jobs(state.get("request") or MatchRequest())
        return {"listings": listings, "warnings": warnings}

    async def score_matches(state: AgentState) -> dict[str, Any]:
        if state.get("errors"):
            return {}
        request = state.get("request") or MatchRequest()
        matches = await ctx.scorer().rank(
            state["profile"],
            state.get("listings") or [],
            llm_top_n=request.llm_top_n,
            min_score=request.min_score,
        )
        return {"matches": matches}

    async def improve_resume_node(state: AgentState) -> dict[str, Any]:
        if state.get("errors"):
            return {}
        targets = [match.listing for match in (state.get("matches") or [])]
        report = await ctx.improver().improve(state.get("profile"), targets)
        return {"report": report}

    async def finalize(state: AgentState) -> dict[str, Any]:
        return {"result": _assemble_result(ctx, state)}

    graph.add_node("load_resume", load_resume)
    graph.add_node("extract_profile", extract_profile)
    graph.add_node("search_jobs", search_jobs_node)
    graph.add_node("score", score_matches)
    graph.add_node("improve", improve_resume_node)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "load_resume")
    graph.add_edge("load_resume", "extract_profile")
    graph.add_edge("extract_profile", "search_jobs")
    graph.add_edge("search_jobs", "score")

    def route_improve(state: AgentState) -> str:
        request = state.get("request") or MatchRequest()
        if request.improve and (state.get("matches") or state.get("errors")):
            return "improve"
        return "finalize"

    graph.add_conditional_edges(
        "score", route_improve, {"improve": "improve", "finalize": "finalize"}
    )
    graph.add_edge("improve", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def _message_dict(role: str, content: str, **extra: Any) -> dict[str, Any]:
    message: dict[str, Any] = {"role": role, "content": content}
    message.update(extra)
    return message


def _to_gateway_message(message: dict[str, Any]) -> Message:
    if message.get("role") == "tool":
        return Message(
            role="tool",
            content=message.get("content", ""),
            tool_call_id=message.get("tool_call_id"),
        )
    tool_calls = message.get("tool_calls")
    if tool_calls:
        return Message(
            role="assistant",
            content=message.get("content", ""),
            tool_calls=tuple(
                ToolCall(id=call["id"], name=call["name"], arguments=call["arguments"])
                for call in tool_calls
            ),
        )
    return Message(role=message["role"], content=message.get("content", ""))


def build_agent(ctx: Any) -> Any:
    """ReAct agent graph powered by conditional routing on tool calls."""

    graph = StateGraph(AgentState)

    async def agent_step(state: AgentState) -> dict[str, Any]:
        messages = [m for m in (state.get("messages") or []) if m.get("role") != "system"]
        if not any(m.get("role") == "system" for m in (state.get("messages") or [])):
            messages.insert(0, _message_dict("system", AGENT_SYSTEM))
        result = await ctx.gateway.chat(
            ctx.provider,
            ctx.model,
            [_to_gateway_message(m) for m in messages],
            tools=AGENT_TOOLS,
        )
        step = state.get("steps", 0) + 1
        if result.tool_calls:
            return {
                "messages": [
                    _message_dict(
                        "assistant",
                        result.content,
                        tool_calls=[
                            {"id": call.id, "name": call.name, "arguments": call.arguments}
                            for call in result.tool_calls
                        ],
                    )
                ],
                "steps": step,
                "final": False,
            }
        ctx.session["final_answer"] = result.content
        return {
            "messages": [_message_dict("assistant", result.content, final=True)],
            "steps": step,
            "final": True,
        }

    async def execute_tools(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        outputs: list[dict[str, Any]] = []
        for call in last.get("tool_calls") or []:
            handler = TOOL_HANDLERS.get(call["name"])
            try:
                payload = (
                    await handler(ctx, call.get("arguments") or {})
                    if handler is not None
                    else {"error": f"unknown tool {call['name']}"}
                )
            except Exception as exc:
                logger.warning("agent tool %s failed: %s", call.get("name"), exc)
                payload = {"error": f"{type(exc).__name__}: {exc}"}
            outputs.append(
                _message_dict(
                    "tool",
                    json.dumps(payload, ensure_ascii=False, default=str),
                    tool_call_id=call.get("id", ""),
                    name=call.get("name", ""),
                )
            )
        return {"messages": outputs}

    async def finalize(state: AgentState) -> dict[str, Any]:
        transcript = [
            m for m in (state.get("messages") or []) if m.get("role") in {"user", "assistant"}
        ]
        return {"result": _assemble_result(ctx, state, transcript=transcript)}

    graph.add_node("agent", agent_step)
    graph.add_node("tools", execute_tools)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "agent")

    def route_agent(state: AgentState) -> str:
        steps = state.get("steps", 0)
        final = bool(state.get("final"))
        if final or steps >= MAX_AGENT_STEPS:
            return "finalize"
        messages = state.get("messages") or []
        if messages and messages[-1].get("tool_calls"):
            return "tools"
        return "finalize"

    graph.add_conditional_edges("agent", route_agent, {"tools": "tools", "finalize": "finalize"})
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
    return graph.compile()
