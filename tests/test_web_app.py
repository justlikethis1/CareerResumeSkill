from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from career_resume_skill import web_app
from career_resume_skill.config import Settings
from career_resume_skill.web_app import create_app


class _FakeApplicationService:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    async def generate_docx_application_package(self, **kwargs):
        resume_docx = Path(kwargs["output_docx"])
        resume_docx.parent.mkdir(parents=True, exist_ok=True)
        baseline = resume_docx.parent / "source-baseline"
        baseline.mkdir()
        (baseline / "source.pdf").write_bytes(b"temporary source PDF")
        resume_docx.write_bytes(b"docx artifact")
        resume_pdf = resume_docx.with_suffix(".pdf")
        resume_pdf.write_bytes(b"resume pdf")
        cover_pdf = resume_docx.parent / "cover-letter.pdf"
        cover_pdf.write_bytes(b"cover pdf")
        cover_txt = resume_docx.parent / "cover-letter.txt"
        cover_txt.write_text("Sincerely", encoding="utf-8")
        cover_md = resume_docx.parent / "cover-letter.md"
        cover_md.write_text("# Cover Letter", encoding="utf-8")
        return {
            "verified": True,
            "warning": None,
            "output_docx": str(resume_docx),
            "output_pdf": str(resume_pdf),
            "cover_letter_pdf": {"pdf_path": str(cover_pdf), "pages": 1},
            "cover_letter_text_path": str(cover_txt),
            "cover_letter_md_path": str(cover_md),
            "quality_report": {"pages": {"output": 1}},
            "ats_report": {
                "score": 82,
                "resume_only": {"score": 74},
                "hard_requirements": {"missing": ["CUDA"]},
                "preferred_keywords": {"missing": []},
            },
            "gap_analysis": {"gaps": ["No source evidence for CUDA"]},
            "performance": {
                "total_seconds": 12.5,
                "stages_seconds": {"docx_import": 1.25, "cover_letter_generation": 4.0},
            },
        }

    async def generate_application_package(self, **kwargs):
        resume_pdf = self.output_dir / "resume.pdf"
        resume_pdf.parent.mkdir(parents=True, exist_ok=True)
        resume_pdf.write_bytes(b"resume pdf")
        letter_pdf = self.output_dir / "cover-letter.pdf"
        letter_pdf.write_bytes(b"cover pdf")
        cover_txt = self.output_dir / "cover-letter.txt"
        cover_txt.write_text("Sincerely", encoding="utf-8")
        cover_md = self.output_dir / "cover-letter.md"
        cover_md.write_text("# Cover Letter", encoding="utf-8")
        return {
            "verified": True,
            "warning": None,
            "documents": {
                "resume": {"pdf_path": str(resume_pdf), "pages": 1},
                "cover_letter": {"pdf_path": str(letter_pdf), "pages": 1},
            },
            "cover_letter_text_path": str(cover_txt),
            "cover_letter_md_path": str(cover_md),
            "ats_report": {"score": 80, "resume_only": {"score": 70}},
            "gap_analysis": {"gaps": []},
            "performance": {
                "total_seconds": 6.0,
                "stages_seconds": {"parallel_resume_and_cover_compilation": 2.5},
            },
        }


def _test_app(tmp_path: Path, captured: dict[str, str]):
    output_dir = tmp_path / "web-output"

    def service_factory(api_key: str, run_dir: Path):
        captured["api_key"] = api_key
        captured["output_dir"] = str(run_dir)
        return _FakeApplicationService(run_dir)

    return create_app(output_dir=output_dir, service_factory=service_factory), output_dir


def test_local_web_form_generates_docx_artifacts_without_persisting_source_or_key(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: Settings(output_dir=str(tmp_path))))
    captured: dict[str, str] = {}
    app, output_dir = _test_app(tmp_path, captured)

    with TestClient(app, base_url="http://127.0.0.1") as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Career Resume Studio" in page.text
        assert "localStorage" not in page.text
        assert 'value="" placeholder="留空时使用通用称谓"' in page.text
        assert '<details class="optional-context field">' in page.text
        assert 'id="show-api-key" type="checkbox"' in page.text
        assert 'apiKeyInput.type = event.target.checked ? "text" : "password"' in page.text
        assert "const missingOutput = !compilerStatus.output_writable" in page.text
        assert "const missingKey = !compilerStatus.api_key_configured && !apiKeyInput.value.trim()" in page.text
        assert "missingOutput || missingKey" in page.text
        response = client.post(
            "/api/applications",
            data={
                "track": "docx",
                "jd_text": "AI research engineer",
                "company_name": "Example Lab",
                "api_key": "one-time-test-key",
                "resume_language": "en",
            },
            files={
                "source_file": (
                    "resume.docx",
                    b"private source resume",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["verified"] is True
        assert result["ats_score"] == 82
        assert result["resume_only_ats_score"] == 74
        assert result["performance"]["total_seconds"] == 12.5
        assert captured["api_key"] == "one-time-test-key"
        assert "one-time-test-key" not in response.text
        assert not list(output_dir.rglob("source.docx"))
        assert not list(output_dir.rglob("source-baseline"))
        download = client.get(f"/api/download/{result['job_id']}/resume_docx")
        assert download.content == b"docx artifact"


def test_local_web_form_supports_master_cv_json_track(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: Settings(output_dir=str(tmp_path))))
    app, _ = _test_app(tmp_path, {})
    master_cv = {"name": "Candidate", "contact": {"email": "candidate@example.com"}}

    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/applications",
            data={"track": "latex", "jd_text": "Software engineer", "api_key": "temporary-key"},
            files={"source_file": ("master-cv.json", json.dumps(master_cv), "application/json")},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["performance"]["stages_seconds"]["parallel_resume_and_cover_compilation"] == 2.5
        assert {artifact["id"] for artifact in result["artifacts"]} == {
            "resume_pdf", "cover_letter_pdf", "cover_letter_txt", "cover_letter_md",
        }


def test_local_web_rejects_cross_site_origin_and_untrusted_host(tmp_path: Path) -> None:
    app, _ = _test_app(tmp_path, {})
    with TestClient(app, base_url="http://127.0.0.1") as client:
        cross_site = client.post(
            "/api/applications",
            headers={"origin": "http://attacker.example"},
            data={"track": "docx"},
        )
        assert cross_site.status_code == 403
        untrusted = client.get("/", headers={"host": "attacker.example"})
        assert untrusted.status_code == 400


def test_local_web_removes_partial_task_files_after_generation_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: Settings(output_dir=str(tmp_path))))
    output_dir = tmp_path / "failed-runs"

    class _FailedService(_FakeApplicationService):
        async def generate_docx_application_package(self, **kwargs):
            partial_file = Path(kwargs["output_docx"])
            partial_file.parent.mkdir(parents=True, exist_ok=True)
            partial_file.write_bytes(b"partial private output")
            raise RuntimeError("generation failed")

    def service_factory(_: str, run_dir: Path):
        return _FailedService(run_dir)

    app = create_app(output_dir=output_dir, service_factory=service_factory)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            "/api/applications",
            data={"track": "docx", "jd_text": "Role", "api_key": "temporary-secret"},
            files={"source_file": ("resume.docx", b"source", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert response.status_code == 422
    assert "temporary-secret" not in response.text
    assert list(output_dir.iterdir()) == []


def test_local_listener_reserves_port_and_skips_occupied_port() -> None:
    listener = web_app._open_local_listener(0, tries=1)
    host, port = listener.getsockname()
    try:
        assert host == "127.0.0.1"
        assert port > 0
        with pytest.raises(RuntimeError, match="没有找到可用的本机网页端口"):
            web_app._open_local_listener(port, tries=1)
    finally:
        listener.close()


def test_environment_reports_xelatex_as_supported_latex_compiler(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: Settings(output_dir=str(tmp_path))))
    monkeypatch.setattr(web_app, "find_compiler", lambda: ("xelatex", ["xelatex"]))
    monkeypatch.setattr(web_app, "environment_report", lambda _: {
        "compilers": {"tectonic": None, "libreoffice": None, "microsoft_word": None},
        "output": {"writable": True},
    })

    with TestClient(create_app(output_dir=tmp_path), base_url="http://127.0.0.1") as client:
        response = client.get("/api/environment")

    assert response.status_code == 200
    assert response.json()["latex_ready"] is True