import asyncio
import json
import time
from copy import deepcopy
from pathlib import Path

import pytest

from career_resume_skill.application import (
    ApplicationService,
    _candidate_technology_source_text,
    _failed_content_critics,
    _score_application_package,
)
from career_resume_skill.cli import _parser, _read_inputs
from career_resume_skill.config import Settings
from career_resume_skill.latex import PageLimitError
from career_resume_skill.quality import lint_output_integrity


class _UnavailableProvider:
    available = False
    model_name = "deterministic_fallback"

    async def complete_json(
        self,
        task: str,
        payload: dict,
        response_model: type,
        temperature: float = 0.2,
    ):
        raise AssertionError("fallback test must not call the provider")


def test_cli_accepts_docx_application_track(tmp_path: Path) -> None:
    source = tmp_path / "resume.docx"
    jd_file = tmp_path / "jd.txt"
    jd_file.write_text("A public-role JD", encoding="utf-8")
    args = _parser().parse_args([
        "--track", "docx", "--docx-template", str(source), "--output-docx",
        str(tmp_path / "tailored.docx"), "--jd-file", str(jd_file), "--company", "Example",
    ])

    jd_source, master_cv, _ = _read_inputs(args)

    assert jd_source == "A public-role JD"
    assert master_cv is None
    assert args.track == "docx"


def test_cli_docx_track_forwards_application_date(monkeypatch, tmp_path: Path) -> None:
    from career_resume_skill import application
    from career_resume_skill import cli as resume_cli

    class _DocxService:
        def __init__(self, settings) -> None:
            pass

        async def generate_docx_application_package(self, **kwargs):
            return kwargs

    monkeypatch.setattr(application, "ApplicationService", _DocxService)
    arguments = _parser().parse_args([
        "--track", "docx", "--docx-template", str(tmp_path / "source.docx"),
        "--output-docx", str(tmp_path / "tailored.docx"), "--jd", "JD text",
        "--company", "Example", "--date", "2026-04-08",
    ])

    result = asyncio.run(resume_cli._run(arguments))

    assert result["application_date"] == "2026-04-08"
    assert result["docx_source"] == str(tmp_path / "source.docx")
    assert result["output_docx"] == str(tmp_path / "tailored.docx")


def test_compile_calls_can_progress_concurrently(monkeypatch, tmp_path: Path) -> None:
    from career_resume_skill import application

    monkeypatch.setattr(application, "render_template", lambda *args, **kwargs: None)

    def fake_compile(path: Path, page_limit: int) -> dict[str, object]:
        time.sleep(0.08)
        return {"pdf_path": str(path.with_suffix(".pdf")), "pages": 1}

    monkeypatch.setattr(application, "compile_latex", fake_compile)
    service = ApplicationService(
        Settings(output_dir=str(tmp_path)), provider=_UnavailableProvider()
    )
    content = {"name": "Candidate", "company_name": "Company"}

    async def run() -> tuple[dict[str, object], dict[str, object], float]:
        started = time.perf_counter()
        results = await asyncio.gather(
            service.render_and_compile_latex("resume", content),
            service.render_and_compile_latex("cover_letter", content),
        )
        return results[0], results[1], time.perf_counter() - started

    resume, cover, elapsed = asyncio.run(run())

    assert resume["pages"] == 1
    assert cover["pages"] == 1
    assert elapsed < 0.14


def test_resume_render_returns_content_after_page_pruning(monkeypatch, tmp_path: Path) -> None:
    from career_resume_skill import application

    monkeypatch.setattr(application, "render_template", lambda *args, **kwargs: None)
    calls = 0

    def fake_compile(path: Path, page_limit: int) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls <= 3:
            raise PageLimitError(2, 1, "overflow")
        return {"pdf_path": str(path.with_suffix(".pdf")), "pages": 1}

    monkeypatch.setattr(application, "compile_latex", fake_compile)
    content = {
        "name": "Candidate", "company_name": "Example",
        "sections": [{"items": [
            {"source_item_id": "hero", "bullets": ["Hero A", "Hero B"],
             "evidence_ids": ["hero:0", "hero:1"]},
            {"source_item_id": "ancillary", "bullets": ["Keep me", "Remove me"],
             "evidence_ids": ["ancillary:0", "ancillary:1"]},
        ]}],
        "strategy": {"item_scores": {"hero": 100, "ancillary": 1}},
    }
    service = ApplicationService(Settings(output_dir=str(tmp_path)), provider=_UnavailableProvider())

    result = asyncio.run(service.render_and_compile_latex(
        "resume", content, page_limit=1, output_dir=tmp_path
    ))

    rendered = result["rendered_content"]
    assert rendered["sections"][0]["items"][0]["bullets"] == ["Hero A", "Hero B"]
    assert rendered["sections"][0]["items"][1]["bullets"] == ["Keep me"]
    assert "Removed low-priority bullet" in result["attempts"][-1]


def test_application_package_uses_pruned_resume_for_metadata_and_integrity(
    monkeypatch, tmp_path: Path
) -> None:
    from career_resume_skill import application

    service = ApplicationService(Settings(output_dir=str(tmp_path)), provider=_UnavailableProvider())
    master_cv = {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "profile": "Python engineer",
        "sections": [{"type": "projects", "title": "Projects", "items": [{
            "title": "Pipeline", "organization": "Example", "dates": "2025",
            "location": "Remote", "bullets": [
                "Built a Python pipeline.", "Measured 12.5% improvement with Python.",
            ],
        }]}],
        "skills": {"Languages": ["Python"]},
    }
    rendered_payloads: list[dict] = []
    integrity_bullets: list[list[str]] = []

    async def fake_render(template_name, content_json, page_limit=1, output_dir=None):
        if template_name == "resume":
            final_content = deepcopy(content_json)
            item = final_content["sections"][0]["items"][0]
            item["bullets"].pop()
            item["evidence_ids"].pop()
            rendered_payloads.append(final_content)
            return {
                "pdf_path": str(tmp_path / "resume.pdf"),
                "tex_path": str(tmp_path / "resume.tex"),
                "pages": 1,
                "compiler": "test",
                "compact_level": 2,
                "attempts": ["Removed low-priority bullet"],
                "rendered_content": final_content,
            }
        return {
            "pdf_path": str(tmp_path / "cover.pdf"),
            "tex_path": str(tmp_path / "cover.tex"),
            "pages": 1,
            "compiler": "test",
            "compact_level": 0,
            "attempts": [],
        }

    def fake_integrity(source, output, pages, **kwargs):
        integrity_bullets.append(kwargs.get("bullet_texts", []))
        return {"passed": True, "checks": {}}

    monkeypatch.setattr(service, "render_and_compile_latex", fake_render)
    monkeypatch.setattr(application, "_pdf_parseability", lambda path: {"page_count": 1})
    monkeypatch.setattr(
        application, "extract_pdf_text",
        lambda path: (1, "\n".join(
            rendered_payloads[0]["sections"][0]["items"][0]["bullets"]
        ) if str(path).endswith("resume.pdf") else "Cover letter."),
    )
    monkeypatch.setattr(application, "lint_output_integrity", fake_integrity)
    monkeypatch.setattr(application, "record_application", lambda *args, **kwargs: {})

    package = asyncio.run(service.generate_application_package(
        "Python pipeline role", master_cv, "Example", page_limit=1,
    ))

    final_bullets = package["tailored_cv"]["sections"][0]["items"][0]["bullets"]
    assert final_bullets == rendered_payloads[0]["sections"][0]["items"][0]["bullets"]
    assert len(final_bullets) == 1
    assert all("12.5%" not in card["text"] for card in package["fact_cards"])
    assert integrity_bullets == [final_bullets, []]


def test_docx_package_returns_cover_letter_and_reports_when_resume_overflows(
    monkeypatch, tmp_path: Path
) -> None:
    from career_resume_skill import application

    master_cv = {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "profile": "Python engineer",
        "sections": [{"type": "projects", "title": "Projects", "items": [{
            "source_item_id": "project-1", "title": "Project", "organization": "Example",
            "location": "Remote", "dates": "2025", "bullets": ["Built a Python API."],
        }]}],
        "skills": {"Languages": ["Python"]},
    }
    imported = {
        "master_cv": master_cv,
        "source_docx": str(tmp_path / "source.docx"),
        "source_item_map": {"project-1": {"bullet_paragraph_ids": ["p:0:body"]}},
    }
    source_docx = tmp_path / "source.docx"
    source_docx.write_bytes(b"source")
    service = ApplicationService(Settings(output_dir=str(tmp_path)), provider=_UnavailableProvider())

    async def async_value(value):
        return value

    monkeypatch.setattr(service, "import_docx_master_cv", lambda path: async_value(imported))
    monkeypatch.setattr(application, "calculate_docx_layout_budget", lambda *args: {"paragraphs": []})
    monkeypatch.setattr(service, "tailor_resume_content", lambda cv, jd: async_value({
        **cv,
        "sections": [{"type": "projects", "title": "Projects", "items": [{
            **cv["sections"][0]["items"][0], "bullets": ["Built a Python API."],
            "evidence_ids": ["project-1:bullet:0"],
        }]}],
        "evidence_gaps": [], "strategy": {}, "gap_analysis": {"gaps": []},
        "model_used": "deterministic_fallback",
    }))
    monkeypatch.setattr(application, "refine_one_bullet", lambda *args, **kwargs: async_value({
        "states": ["INGESTION", "PROJECTION", "GEOMETRIC_EVALUATION"],
        "outcome": "offline_no_patch",
    }))
    monkeypatch.setattr(application, "lint_payload_bullets", lambda *args, **kwargs: {
        "passed": True, "missing_metrics": [], "invalid_bullet_indices": [],
        "private_use_codepoints": [],
    })

    def fake_inject(source, output, groups, **kwargs):
        Path(output).write_bytes(b"tailored")
        return Path(output)

    monkeypatch.setattr(application, "inject_docx_bullet_groups", fake_inject)

    async def fake_convert(path, output_dir=None):
        pdf_path = Path(path).with_suffix(".pdf")
        pdf_path.write_bytes(b"pdf")
        return {"pdf_path": str(pdf_path)}

    monkeypatch.setattr(service, "convert_docx_to_pdf", fake_convert)
    monkeypatch.setattr(application, "extract_pdf_text", lambda path: (
        (1, "Source resume.") if "source-baseline" in str(path) else (2, "Tailored resume with Python.")
    ))
    monkeypatch.setattr(service, "draft_cover_letter", lambda *args, **kwargs: async_value({
        "salutation": "Dear Hiring Team,", "paragraphs": ["First.", "Second.", "Third."],
        "closing": "Regards", "evidence_ids": ["project-1:bullet:0"],
        "evidence_gaps": [], "model_used": "deterministic_fallback",
    }))
    async def fake_render_letter(*args, **kwargs):
        cover_pdf = tmp_path / "cover-letter.pdf"
        cover_pdf.write_bytes(b"pdf")
        return {"pdf_path": str(cover_pdf), "pages": 1}

    monkeypatch.setattr(service, "render_and_compile_latex", fake_render_letter)
    monkeypatch.setattr(application, "document_quality_report", lambda *args, **kwargs: {
        "pages": {"source": 1, "output": 2},
        "pdf": {"output": {"characters": 32}},
        "visual_layout": {}, "diagnosis": {},
        "ats_readability": {"ats_readability_flags": []},
    })
    monkeypatch.setattr(application, "record_application", lambda *args, **kwargs: pytest.fail(
        "Unverified page-overflow package must not be written to the delivery ledger"
    ))

    package = asyncio.run(service.generate_docx_application_package(
        str(source_docx), "Python role", str(tmp_path / "output.docx"), "Example Co"
    ))

    assert package["verified"] is False
    assert "did not pass final verification" in package["warning"]
    assert package["quality_report"]["integrity_linter"]["checks"]["page_budget"]["actual"] == 2
    assert Path(package["cover_letter_pdf"]["pdf_path"]).is_file()
    assert Path(package["cover_letter_text_path"]).is_file()
    assert Path(package["cover_letter_md_path"]).is_file()
    assert package["ats_report"]["delivery_verified"] is False
    assert package["ledger_entry"] is None


def test_delivery_gate_includes_failed_content_critics() -> None:
    assert _failed_content_critics({
        "cover_letter_critic": {"passed": False, "issues": ["cross_paragraph_repetition"]},
        "resume_content_critic": {"passed": True},
    }) == ["cover_letter_critic"]
    assert not _failed_content_critics({"cover_letter_critic": {"passed": True}})


def test_integrity_source_includes_candidate_profile_links_as_technology_provenance() -> None:
    source = _candidate_technology_source_text({
        "name": "Candidate",
        "contact": {
            "email": "candidate@example.com",
            "github": "https://github.com/candidate",
            "linkedin": "https://linkedin.com/in/candidate",
        },
        "skills": {},
        "sections": [],
    })
    report = lint_output_integrity(
        source,
        "GitHub | LinkedIn",
        1,
        expected_pages=1,
        source_technology_text=source,
    )

    assert report["checks"]["technology_provenance"]["passed"] is True


def test_application_runs_get_unique_output_directories(tmp_path: Path) -> None:
    master_cv = json.loads(Path("examples/master_cv.json").read_text(encoding="utf-8"))
    service = ApplicationService(
        Settings(output_dir=str(tmp_path)), provider=_UnavailableProvider()
    )

    async def run_twice() -> tuple[dict[str, object], dict[str, object]]:
        first = await service.generate_application_package(
            "AI Lab requires Python and PyTorch",
            master_cv,
            "Example Lab",
            compile_documents=False,
        )
        second = await service.generate_application_package(
            "AI Lab requires Python and PyTorch",
            master_cv,
            "Example Lab",
            compile_documents=False,
        )
        return first, second

    first, second = asyncio.run(run_twice())

    assert first["run_id"] != second["run_id"]
    assert first["run_dir"] != second["run_dir"]
    assert Path(first["run_dir"]).is_dir()
    assert Path(second["run_dir"]).is_dir()
    cover_text = Path(first["cover_letter_text_path"]).read_text(encoding="utf-8")
    assert first["cover_letter"]["paragraphs"][0] in cover_text
    assert "RE: Application for AI Research - Candidate" in cover_text


def test_offline_tailoring_preserves_docx_source_item_id() -> None:
    master_cv = {
        "name": "Candidate",
        "contact": {"email": "candidate@example.com"},
        "sections": [{"type": "projects", "title": "Projects", "items": [{
            "source_item_id": "p:3:body",
            "title": "Pipeline",
            "bullets": ["Built a Python pipeline by 5.2%."],
        }]}],
    }
    service = ApplicationService(Settings(), provider=_UnavailableProvider())

    tailored = asyncio.run(service.tailor_resume_content(
        master_cv, {"role_type": "data_engineering", "must_haves": ["Python"]}
    ))
    item = tailored["sections"][0]["items"][0]

    assert item["source_item_id"] == "p:3:body"
    assert item["evidence_ids"] == ["p:3:body:bullet:0"]


def test_enhanced_jd_analysis_keeps_long_clauses_out_of_ats_keywords(monkeypatch) -> None:
    from career_resume_skill import application

    long_clause = "具备较强的工程实现、实验分析和问题定位能力，能够将算法方案转化为稳定可复现的训练流程"

    class AnalysisProvider:
        available = True
        model_name = "test-model"

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            return response_model.model_validate({
                "role_type": "ai_research",
                "must_haves": ["Python", long_clause],
                "nice_to_haves": [],
                "ats_keywords": ["Python", long_clause],
            })

    async def resolved(source):
        return source, {"kind": "text", "value": "inline"}

    monkeypatch.setattr(application, "resolve_jd_source", resolved)
    service = ApplicationService(Settings(), provider=AnalysisProvider())

    analysis = asyncio.run(service.analyze_job_description("Python engineering role"))

    assert analysis["must_haves"] == ["Python"]
    assert analysis["ats_keywords"] == ["Python"]
    assert long_clause in analysis["excluded_non_atomic_requirements"]


def test_enhanced_jd_analysis_keeps_atomic_terms_and_audits_sentence_requirements(
    monkeypatch,
) -> None:
    from career_resume_skill import application

    sentence_requirement = "具备较强的工程实现、实验分析和问题定位能力，能够将算法方案转化为稳定可复现的训练流程"

    class Provider:
        available = True
        model_name = "test-model"

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            return response_model.model_validate({
                "role_type": "ai_research",
                "must_haves": ["PPO", sentence_requirement],
                "nice_to_haves": [],
                "ats_keywords": ["PPO", sentence_requirement],
            })

    async def resolve(source):
        return source, {"kind": "text", "value": "inline"}

    monkeypatch.setattr(application, "resolve_jd_source", resolve)
    service = ApplicationService(Settings(), provider=Provider())
    analysis = asyncio.run(service.analyze_job_description("AI research role"))

    assert analysis["must_haves"] == ["PPO"]
    assert analysis["ats_keywords"] == ["PPO"]
    assert sentence_requirement in analysis["excluded_non_atomic_requirements"]


def test_chinese_docx_requires_model_before_reading_input(tmp_path: Path) -> None:
    service = ApplicationService(Settings(output_dir=str(tmp_path)), provider=_UnavailableProvider())
    with pytest.raises(ValueError, match="configured LLM provider"):
        asyncio.run(service.generate_docx_application_package(
            str(tmp_path / "missing.docx"), "JD", str(tmp_path / "output.docx"),
            "Example", resume_language="zh_CN",
        ))


def test_application_ats_score_includes_cover_letter_and_preserves_resume_subscore() -> None:
    jd_analysis = {
        "must_haves": ["reliable inference pipelines"],
        "hard_skills": [],
        "nice_to_haves": [],
        "ats_keywords": [],
    }
    resume = {
        "name": "Candidate",
        "contact": {"email": "candidate@example.com"},
        "sections": [],
        "skills": {},
    }
    cover_letter = {
        "paragraphs": [
            "I built a reliable inference pipeline supported by measured evaluation.",
        ]
    }

    report = _score_application_package(jd_analysis, resume, cover_letter)

    assert report["scoring_scope"] == "resume_and_cover_letter"
    assert report["hard_requirements"]["missing"] == []
    assert report["resume_only"]["hard_requirements"]["missing"] == [
        "reliable inference pipelines",
    ]
