"""Command-line interface for the job-matcher agent."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

import typer
from rich.console import Console
from rich.table import Table

from .domain.models import MatchRequest
from .report import render_report, save_report
from .service import JobMatchService, build_gateway

app = typer.Typer(
    name="jobmatcher",
    help="Analyze resumes, find live jobs, score fit, and improve profiles.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)

_RESUME_EXTS = (".pdf", ".docx", ".txt", ".md", ".rst")


_T = TypeVar("_T")


def _run(coro: Coroutine[Any, Any, _T]) -> _T:
    return asyncio.run(coro)


def _resume_text_from(resume: str | None, text: str | None) -> str:
    if resume:
        path = Path(resume)
        if not path.exists():
            raise typer.BadParameter(f"resume file not found: {resume}")
        return path.read_text(encoding="utf-8", errors="replace")
    if text:
        return text
    raise typer.BadParameter("provide --resume <file> or --text <content>")


@app.command()
def providers() -> None:
    """List the LLM providers available in the gateway registry."""
    gateway = build_gateway()
    table = Table(title="Gateway providers")
    table.add_column("id")
    table.add_column("protocol")
    table.add_column("base_url")
    for provider_id in gateway.registry.ids():
        provider = gateway.registry.get(provider_id)
        table.add_row(
            provider_id,
            provider.protocol,
            provider.base_url,
        )
    console.print(table)


@app.command()
def analyze(
    resume: str | None = typer.Option(
        None, "--resume", "-r", help="Path to a resume pdf/docx/txt/md."
    ),
    text: str | None = typer.Option(None, "--text", "-t", help="Resume content inline."),
    save: bool = typer.Option(False, "--save", help="Persist the structured profile as JSON."),
) -> None:
    """Parse a resume into a structured candidate profile."""
    service = JobMatchService()
    analysis = _run(service.analyze(_resume_text_from(resume, text)))
    profile = analysis.profile
    console.print(
        f"[bold]{profile.contact.name or 'Candidate'}[/bold]"
        f" · {profile.contact.email or 'no email'} · {profile.contact.location or 'no location'}"
    )
    if profile.summary:
        console.print(profile.summary)
    console.print(f"\nYears of experience: [green]{profile.years_experience or 'unknown'}[/green]")
    console.print(f"Target titles: {', '.join(profile.target_titles) or '—'}")
    console.print(
        f"\n[bold]Hard skills ({len(profile.hard_skills)})[/bold]: "
        f"{', '.join(sorted(profile.hard_skills))}"
    )
    if profile.experience:
        console.print("\n[bold]Experience[/bold]")
        for entry in profile.experience:
            console.print(
                f"- {entry.title or '—'} @ {entry.company or '—'} "
                f"({entry.start_date or '—'}→{entry.end_date or 'now'})"
            )
    for warning in analysis.warnings:
        err_console.print(f"[yellow]warning:[/yellow] {warning}")
    if save:
        output = Path("reports") / "profile.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        console.print(f"\nProfile saved to {output}")


@app.command()
def search(
    query: str = typer.Argument(..., help="Free-text search keywords."),
    location: str = typer.Option("", "--location", "-l"),
    remote_only: bool = typer.Option(False, "--remote", help="Fully remote only."),
    limit: int = typer.Option(40, "--limit", min=1, max=500),
    sources: str | None = typer.Option(
        None, "--source", help="Comma-separated source ids (remotive,greenhouse,lever,usajobs)."
    ),
) -> None:
    """Fetch job listings from live internet boards."""
    request = MatchRequest(
        query=query,
        location=location,
        remote_only=remote_only,
        limit=limit,
        sources=[s.strip() for s in sources.split(",")] if sources else None,
    )
    result = _run(JobMatchService().search(request))
    table = Table(title=f"{result.jobs_retrieved} jobs for {query!r}")
    table.add_column("Source")
    table.add_column("Title")
    table.add_column("Company")
    table.add_column("Location")
    for listing in result.listings:
        table.add_row(listing.source, listing.title, listing.company, listing.location or "—")
    console.print(table)
    for warning in result.warnings:
        err_console.print(f"[yellow]warning:[/yellow] {warning}")


@app.command()
def match(
    resume: str | None = typer.Option(None, "--resume", "-r"),
    text: str | None = typer.Option(None, "--text", "-t"),
    query: str = typer.Option("", "--query", "-q", help="Keywords to steer the job search."),
    location: str = typer.Option("", "--location", "-l"),
    remote_only: bool = typer.Option(False, "--remote"),
    limit: int = typer.Option(50, "--limit", min=1, max=500),
    llm_top_n: int = typer.Option(15, "--llm-top-n", help="How many listings get model scoring."),
    min_score: float = typer.Option(
        30.0, "--min-score", help="Reject matches below this fit score."
    ),
    no_improve: bool = typer.Option(False, "--no-improve", help="Skip the improvement report."),
    save: bool = typer.Option(False, "--save", help="Write Markdown + JSON reports to reports/."),
) -> None:
    """Full pipeline: resume analysis + job search + scoring + improvements."""
    request = MatchRequest(
        resume_text=_resume_text_from(resume, text),
        query=query,
        location=location,
        remote_only=remote_only,
        limit=limit,
        llm_top_n=llm_top_n,
        min_score=min_score,
        improve=not no_improve,
    )
    result = _run(JobMatchService().match(request))
    console.print(render_report(result))
    if save:
        md_path, json_path = save_report(result)
        console.print(f"\n[green]Saved:[/green] {md_path} and {json_path}")


@app.command()
def improve(
    resume: str | None = typer.Option(None, "--resume", "-r"),
    text: str | None = typer.Option(None, "--text", "-t"),
    query: str = typer.Option("", "--query", "-q", help="Keywords to steer the target-job search."),
    location: str = typer.Option("", "--location", "-l"),
    targets: int = typer.Option(3, "--targets", help="Top-N jobs to optimize against."),
) -> None:
    """Produce a resume-improvement plan against the top matched jobs."""
    request = MatchRequest(
        resume_text=_resume_text_from(resume, text),
        query=query,
        location=location,
        limit=30,
        llm_top_n=targets,
        min_score=0.0,
        improve=True,
    )
    result = _run(JobMatchService().match(request))
    console.print(render_report(result))


@app.command()
def agent(
    resume: str | None = typer.Option(None, "--resume", "-r"),
    text: str | None = typer.Option(None, "--text", "-t"),
    question: str = typer.Option(
        "", "--question", "-q", help="Natural-language goal for the agent."
    ),
    query: str = typer.Option("", "--query", help="Search keywords to seed the request."),
) -> None:
    """Run the autonomous ReAct agent with tool-calling."""
    service = JobMatchService()
    request = MatchRequest(
        resume_path=resume,
        resume_text=text,
        query=query,
    )
    result = _run(service.agent(request, question))
    console.print(render_report(result))


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Run the FastAPI HTTP server."""
    import uvicorn

    from .server.app import create_app

    uvicorn.run(create_app(), host=host, port=port, reload=reload)


def _entrypoint() -> None:
    app()


if __name__ == "__main__":
    app()
