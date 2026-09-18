"""Tests for the FastAPI server (wiring, auth, error mapping)."""

from __future__ import annotations

import io
from typing import ClassVar

from fastapi.testclient import TestClient
from tests.conftest import sample_listings, sample_profile

from gateway.errors import AuthenticationError, BudgetExceeded
from jobmatcher.config import Settings
from jobmatcher.domain.models import MatchResult, ResumeAnalysis, SearchResult
from jobmatcher.server.app import AgentRequest, create_app


class StubService:
    provider = "zen"
    model = "gpt-test"

    @staticmethod
    async def analyze(resume_text: str) -> ResumeAnalysis:
        return ResumeAnalysis(profile=sample_profile(), warnings=[])

    @staticmethod
    async def search(request) -> SearchResult:
        return SearchResult(jobs_retrieved=1, listings=sample_listings()[:1], warnings=[])

    @staticmethod
    async def match(request) -> MatchResult:
        return MatchResult(profile=sample_profile(), jobs_retrieved=1, matches=[], warnings=[])

    @staticmethod
    async def agent(request, question: str = "") -> MatchResult:
        return MatchResult(
            profile=sample_profile(), jobs_retrieved=1, matches=[], warnings=[question]
        )


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, _env_file_override=True, **overrides)


def _client(**overrides) -> TestClient:
    app = create_app(_settings(**overrides))
    app.state.service = StubService()
    return TestClient(app)


def test_health_reports_provider_and_sources():
    client = _client()
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider"] == "zen"
    assert body["model"] == "gpt-test"
    assert "remotive" in body["sources"]


def test_analyze_returns_profile():
    client = _client()
    response = client.post("/api/v1/analyze", json={"resume_text": "Jane Doe\npython, sql"})
    assert response.status_code == 200
    assert response.json()["profile"]["contact"]["name"] == "Jane Doe"


def test_analyze_rejects_missing_resume():
    client = _client()
    response = client.post("/api/v1/analyze", json={"query": "data"})
    assert response.status_code == 422


def test_search_and_match_and_agent_endpoints():
    client = _client()
    assert client.post("/api/v1/search", json={"query": "data"}).status_code == 200
    assert client.post("/api/v1/match", json={"resume_text": "resume"}).status_code == 200
    response = client.post("/api/v1/agent", json={"resume_text": "resume", "question": "hello"})
    assert response.status_code == 200
    assert response.json()["warnings"] == ["hello"]


def test_agent_requires_question_field_optional():
    client = _client()
    body = AgentRequest(resume_text="resume").model_dump()
    response = client.post("/api/v1/agent", json=body)
    assert response.status_code == 200
    assert response.json()["warnings"] == [""]


def test_auth_blocks_requests_without_key():
    client = _client(server_api_key="sekret")
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer sekret"}).status_code == 200
    assert client.get("/health", headers={"X-API-Key": "sekret"}).status_code == 200


def test_no_auth_when_key_absent():
    client = _client(server_api_key=None)
    assert client.get("/health").status_code == 200


def test_gateway_authentication_error_maps_to_401():
    from jobmatcher.server.app import create_app as _create_app

    class AuthFailService(StubService):
        @staticmethod
        async def analyze(resume_text: str) -> ResumeAnalysis:
            raise AuthenticationError("bad key")

    app = _create_app(_settings())
    app.state.service = AuthFailService()
    client = TestClient(app)
    response = client.post("/api/v1/analyze", json={"resume_text": "text"})
    assert response.status_code == 401


def test_budget_exceeded_maps_to_429():
    class BrokeService(StubService):
        @staticmethod
        async def match(request) -> MatchResult:
            raise BudgetExceeded(limit_usd=5.0, spent_usd=5.01)

    app = create_app(_settings())
    app.state.service = BrokeService()
    client = TestClient(app)
    response = client.post("/api/v1/match", json={"resume_text": "text"})
    assert response.status_code == 429


def test_limit_is_capped():
    class RecordingService(StubService):
        seen_limits: ClassVar[list[int]] = []

        @classmethod
        async def search(cls, request) -> SearchResult:
            cls.seen_limits.append(request.limit)
            return SearchResult(jobs_retrieved=0, listings=[], warnings=[])

    app = create_app(_settings())
    app.state.service = RecordingService()
    client = TestClient(app)
    response = client.post("/api/v1/search", json={"query": "data", "limit": 5000})
    assert response.status_code == 200
    assert RecordingService.seen_limits == [200]


def test_static_spa_is_served_at_root():
    client = _client()
    index = client.get("/")
    assert index.status_code == 200
    assert 'id="root"' in index.text

    import re

    assets = re.findall(r"/(assets/[A-Za-z0-9._-]+\.(?:js|css))", index.text)
    assert assets, f"no bundled assets referenced in {index.text[:300]}"
    for asset in assets:
        assert client.get(f"/{asset}").status_code == 200, f"missing {asset}"

    js = client.get(f"/{next(a for a in assets if a.endswith('.js'))}")
    assert "/api/v1/upload" in js.text
    assert "/api/v1/cv/export" in js.text


def _export(client: TestClient, upload_id: str, text: str, as_format: str | None = None):
    return client.post(
        "/api/v1/cv/export",
        json={"upload_id": upload_id, "text": text, "as_format": as_format},
    )


def test_upload_extracts_text_and_export_round_trips(tmp_path):
    client = _client(report_dir=str(tmp_path))
    text = "Jordan Blake\n\nSKILLS\n- python\n- kafka"
    uploaded = client.post(
        "/api/v1/upload",
        files={"file": ("cv.txt", text.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["extension"] == "txt"
    assert body["text"] == text

    edited = text.replace("- kafka", "- kafka\\n- gRPC")
    exported = _export(client, body["upload_id"], edited)
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/plain")
    assert exported.content.decode("utf-8") == edited

    docx = _export(client, body["upload_id"], edited, "docx")
    assert docx.status_code == 200
    assert docx.content[:2] == b"PK"

    pdf = _export(client, body["upload_id"], edited, "pdf")
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"


def test_upload_rejects_unsupported_and_unknown_export(tmp_path):
    client = _client(report_dir=str(tmp_path))
    payload = {"file": ("cv.exe", b"x", "application/octet-stream")}
    assert client.post("/api/v1/upload", files=payload).status_code == 415
    assert _export(client, "a" * 32, "x").status_code == 404
    assert _export(client, "a" * 32, "x", "xyz").status_code == 404


def _upload_pdf(client: TestClient, text: str = "AI / ML Developer with Python"):
    import io

    from reportlab.pdfgen import canvas as rlcanvas

    buffer = io.BytesIO()
    c = rlcanvas.Canvas(buffer, pagesize=(595.0, 842.0))
    c.setFont("Helvetica", 12)
    c.drawString(72, 800, text)
    c.showPage()
    c.save()
    return client.post(
        "/api/v1/upload",
        files={"file": ("cv.pdf", buffer.getvalue(), "application/pdf")},
    )


def test_original_file_endpoint_returns_stored_bytes(tmp_path):
    client = _client(report_dir=str(tmp_path))
    uploaded = _upload_pdf(client)
    assert uploaded.status_code == 200, uploaded.text
    upload_id = uploaded.json()["upload_id"]

    fetched = client.get(f"/api/v1/cv/{upload_id}/file")
    assert fetched.status_code == 200
    assert fetched.headers["content-type"].startswith("application/pdf")
    assert fetched.content[:4] == b"%PDF"
    assert fetched.headers["content-disposition"].startswith("inline")


def test_positions_endpoint_reports_editable_pdf(tmp_path):
    client = _client(report_dir=str(tmp_path))
    upload_id = _upload_pdf(client).json()["upload_id"]
    body = client.get(f"/api/v1/cv/{upload_id}/positions").json()
    assert body["editable"] is True
    assert body["extension"] == "pdf"
    assert len(body["pages"]) == 1
    words = [w["text"] for w in body["pages"][0]["words"]]
    assert "Developer" in words


def test_positions_endpoint_reports_non_editable_docx(tmp_path):
    import docx

    client = _client(report_dir=str(tmp_path))
    document = docx.Document()
    document.add_paragraph("AI / ML Developer with Python")
    buffer = io.BytesIO()
    document.save(buffer)
    uploaded = client.post(
        "/api/v1/upload",
        files={
            "file": (
                "cv.docx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    upload_id = uploaded.json()["upload_id"]
    body = client.get(f"/api/v1/cv/{upload_id}/positions").json()
    assert body["editable"] is False
    assert body["pages"] == []


def test_export_patches_pdf_in_place_when_changes_are_placeable(tmp_path):
    client = _client(report_dir=str(tmp_path))
    upload_id = _upload_pdf(client).json()["upload_id"]
    original = client.get(f"/api/v1/cv/{upload_id}/file").content

    exported = _export(client, upload_id, "AI / ML Engineer with Python", "pdf")
    assert exported.status_code == 200
    assert exported.content[:4] == b"%PDF"
    assert "patched in place" in exported.headers["x-patch-notes"]
    assert exported.content != original

    import io as _io

    import pymupdf

    with pymupdf.open(stream=_io.BytesIO(exported.content), filetype="pdf") as doc:
        text = doc[0].get_text()
        assert "Engineer" in text
        assert "with Python" in text
        assert "Developer" not in text


def test_export_pdf_without_changes_returns_original_bytes(tmp_path):
    client = _client(report_dir=str(tmp_path))
    upload_id = _upload_pdf(client).json()["upload_id"]
    original = client.get(f"/api/v1/cv/{upload_id}/file").content
    same = _export(client, upload_id, "AI / ML Developer with Python", "pdf")
    assert same.status_code == 200
    assert same.content == original
    assert "x-patch-notes" not in same.headers


def test_export_pdf_as_other_format_reflows_txt_flow(tmp_path):
    client = _client(report_dir=str(tmp_path))
    upload_id = _upload_pdf(client).json()["upload_id"]
    exported = _export(client, upload_id, "AI / ML Engineer with Python", "docx")
    assert exported.status_code == 200
    assert exported.content[:2] == b"PK"
    assert "x-patch-notes" not in exported.headers
