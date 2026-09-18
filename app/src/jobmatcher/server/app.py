"""FastAPI application exposing the job-matcher agent over HTTP.

Endpoints:
- ``GET /health`` — liveness + provider info.
- ``POST /api/v1/analyze`` — resume -> structured profile.
- ``POST /api/v1/search`` — live job search (no matching).
- ``POST /api/v1/match`` — full pipeline (analyze + search + score + improve).
- ``POST /api/v1/agent`` — autonomous ReAct agent for natural-language goals.
- ``POST /api/v1/report`` — like match, but persists Markdown/JSON to disk.
- ``GET /`` — static single-page UI (analyze / search / match / agent).

Auth: when ``SERVER_API_KEY`` is set every request must carry
``Authorization: Bearer <key>`` (or ``X-API-Key``). Rate limiting is an
in-memory sliding window keyed by client IP.

Dependencies are injected through ``app.state`` so tests can swap in stubs.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from gateway.errors import (
    AuthenticationError,
    BudgetExceeded,
    GatewayError,
)

from ..config import Settings, get_settings
from ..domain.models import (
    ExportRequest,
    MatchRequest,
    MatchResult,
    PdfPageBoxes,
    PdfPositionsResult,
    PdfWordBox,
    ResumeAnalysis,
    SearchResult,
    UploadResult,
)
from ..report import save_report
from ..resume.parsers import SUPPORTED_EXTENSIONS, extract_text
from ..service import JobMatchService
from .uploads import CONTENT_TYPES, MAX_UPLOAD_BYTES, UploadStore

logger = logging.getLogger("jobmatcher.server")

_STATIC_DIR = Path(__file__).parent / "static"

_MAX_LIMIT = 200
_RATE_WINDOW_SECONDS = 60


class AgentRequest(MatchRequest):
    question: str = ""


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: int = _RATE_WINDOW_SECONDS) -> None:
        self.max_requests = max_requests
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        queue = self._hits[key]
        while queue and now - queue[0] > self.window:
            queue.popleft()
        if len(queue) >= self.max_requests:
            return False
        queue.append(now)
        return True


def _map_gateway_error(exc: GatewayError) -> HTTPException:
    if isinstance(exc, AuthenticationError):
        return HTTPException(
            status_code=401, detail=str(exc.args[0]) if exc.args else "authentication failed"
        )
    if isinstance(exc, BudgetExceeded):
        return HTTPException(status_code=429, detail="LLM cost budget exceeded")
    return HTTPException(
        status_code=502, detail=f"upstream LLM provider error: {type(exc).__name__}"
    )


def get_service(request: Request) -> JobMatchService:
    return cast(JobMatchService, request.app.state.service)


SERVICE_DEP = Depends(get_service)
UPLOAD_FILE = File()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    limiter = SlidingWindowLimiter(settings.server_rate_limit_per_min)

    def require_rate(request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        if not limiter.allow(key):
            raise HTTPException(status_code=429, detail="rate limit exceeded, slow down")

    def require_auth(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None),
    ) -> None:
        if not settings.server_api_key:
            return
        provided = x_api_key
        if authorization and authorization.lower().startswith("bearer "):
            provided = authorization.split(" ", 1)[1]
        if not provided or provided != settings.server_api_key:
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    dependencies: Sequence[Any] = [Depends(require_rate)]
    if settings.server_api_key:
        dependencies = [*dependencies, Depends(require_auth)]

    app = FastAPI(
        title="jobmatcher",
        version="0.1.0",
        description="Agentic job matching and resume improvement.",
        dependencies=dependencies,
    )
    app.state.settings = settings
    app.state.service = JobMatchService(settings)

    def _guard(body: MatchRequest) -> MatchRequest:
        if body.limit > _MAX_LIMIT:
            body = body.model_copy(update={"limit": _MAX_LIMIT})
        return body

    def _resume_text(body: MatchRequest) -> str:
        if body.resume_text:
            return body.resume_text
        if body.resume_path:
            return extract_text(body.resume_path)
        raise HTTPException(status_code=422, detail="provide resume_text or resume_path")

    @app.get("/health")
    async def health(service: JobMatchService = SERVICE_DEP) -> dict[str, object]:
        return {
            "status": "ok",
            "provider": service.provider,
            "model": service.model,
            "sources": settings.job_source_ids,
            "cost_limit_usd": settings.llm_cost_limit_usd,
        }

    @app.post("/api/v1/analyze", response_model=ResumeAnalysis)
    async def analyze(
        body: MatchRequest,
        service: JobMatchService = SERVICE_DEP,
    ) -> ResumeAnalysis:
        try:
            return await service.analyze(_resume_text(body))
        except GatewayError as exc:
            raise _map_gateway_error(exc) from exc

    @app.post("/api/v1/search", response_model=SearchResult)
    async def search(
        body: MatchRequest,
        service: JobMatchService = SERVICE_DEP,
    ) -> SearchResult:
        return await service.search(_guard(body))

    @app.post("/api/v1/match", response_model=MatchResult)
    async def match(
        body: MatchRequest,
        service: JobMatchService = SERVICE_DEP,
    ) -> MatchResult:
        try:
            return await service.match(_guard(body))
        except GatewayError as exc:
            raise _map_gateway_error(exc) from exc

    @app.post("/api/v1/agent", response_model=MatchResult)
    async def agent(
        body: AgentRequest,
        service: JobMatchService = SERVICE_DEP,
    ) -> MatchResult:
        try:
            return await service.agent(_guard(body), body.question)
        except GatewayError as exc:
            raise _map_gateway_error(exc) from exc

    @app.post("/api/v1/report", response_model=MatchResult)
    async def report(
        body: MatchRequest,
        service: JobMatchService = SERVICE_DEP,
    ) -> MatchResult:
        try:
            result = await service.match(_guard(body))
            md_path, json_path = save_report(result, settings.report_dir)
            logger.info("saved report: %s / %s", md_path, json_path)
            return result
        except GatewayError as exc:
            raise _map_gateway_error(exc) from exc

    uploads = UploadStore(settings.report_dir)

    @app.post("/api/v1/upload", response_model=UploadResult)
    async def upload_resume(
        file: UploadFile = UPLOAD_FILE,
    ) -> UploadResult:
        extension = Path(file.filename or "").suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"unsupported resume format '{extension or '(none)'}' "
                    f"(supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))})"
                ),
            )
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"resume too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
            )
        try:
            record = uploads.save(file.filename or f"resume{extension}", data)
            text = extract_text(record.path)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"could not extract resume: {exc}") from exc
        return UploadResult(
            upload_id=record.upload_id,
            filename=record.filename,
            extension=record.extension.lstrip("."),
            text=text,
        )

    @app.post("/api/v1/cv/export")
    async def export_cv(body: ExportRequest) -> Response:
        try:
            data, filename, content_type, notes = uploads.render(
                body.upload_id, body.text, body.as_format
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="upload not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        if notes:
            headers["X-Patch-Notes"] = "; ".join(notes)
        return Response(content=data, media_type=content_type, headers=headers)

    @app.get("/api/v1/cv/{upload_id}/file")
    async def original_file(upload_id: str) -> Response:
        try:
            record = uploads.record(upload_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="upload not found") from exc
        extension = record.extension.lower()
        content_type = CONTENT_TYPES.get(extension, "application/octet-stream")
        return Response(
            content=record.path.read_bytes(),
            media_type=content_type,
            headers={"Content-Disposition": f'inline; filename="{record.filename}"'},
        )

    @app.get("/api/v1/cv/{upload_id}/positions", response_model=PdfPositionsResult)
    async def positions(upload_id: str) -> PdfPositionsResult:
        try:
            record = uploads.record(upload_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="upload not found") from exc
        editable = record.extension.lower() == ".pdf"
        pages: list[PdfPageBoxes] = []
        if editable:
            from ..pdfpatch import extract_word_boxes

            for page in extract_word_boxes(record.path):
                pages.append(
                    PdfPageBoxes(
                        page=page.page,
                        width=page.width,
                        height=page.height,
                        words=[
                            PdfWordBox(
                                x0=word.x0,
                                y0=word.y0,
                                x1=word.x1,
                                y1=word.y1,
                                oy=word.oy,
                                text=word.text,
                                size=word.size,
                                font=word.font,
                            )
                            for word in page.words
                        ],
                    )
                )
        return PdfPositionsResult(
            upload_id=upload_id,
            extension=record.extension.lstrip("."),
            editable=editable,
            pages=pages,
        )

    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")

    return app


app = create_app()
