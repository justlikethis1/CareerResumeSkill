import asyncio
import re
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfReader

from career_resume_skill.application import ApplicationService
from career_resume_skill.config import Settings
from career_resume_skill.quality import extract_pdf_text
from career_resume_skill.tools import find_libreoffice, find_tectonic


class _Offline:
    available = False
    model_name = "deterministic_fallback"


@pytest.mark.parametrize("role,jd", [
    ("quant_cplusplus_hft", "Quant C++ low latency Python market systems"),
    ("ai_lab_rlhf_dpo", "AI Lab RLHF DPO PyTorch alignment research"),
    ("systems_distributed_backend", "Distributed Python systems high throughput backend"),
])
def test_golden_docx_application_package(tmp_path: Path, role: str, jd: str) -> None:
    if find_libreoffice() is None or find_tectonic() is None:
        pytest.skip("Golden PDF test needs LibreOffice and Tectonic")
    source = tmp_path / "source.docx"
    document = Document()
    for line in (
        "Candidate", "candidate@example.com", "PROJECTS", "Verified Research",
        "Published IEEE ICEICT work using Python with a 5.2% gain and 12.5% error.",
        "Built a BERT pipeline with sub-10ms intent recognition.",
    ):
        document.add_paragraph(line)
    document.save(source)
    service = ApplicationService(Settings(output_dir=str(tmp_path)), provider=_Offline())

    package = asyncio.run(service.generate_docx_application_package(
        str(source), jd, str(tmp_path / f"{role}.docx"), f"Example {role}",
        application_date="2026-04-08",
    ))
    _, pdf_text = extract_pdf_text(package["output_pdf"])
    _, cover_pdf_text = extract_pdf_text(package["cover_letter_pdf"]["pdf_path"])

    assert len(PdfReader(package["output_pdf"]).pages) == 1
    assert len(PdfReader(package["cover_letter_pdf"]["pdf_path"]).pages) == 1
    assert all(term in pdf_text for term in ("5.2%", "12.5%", "sub-10ms", "IEEE ICEICT"))
    assert not any("\ue000" <= char <= "\uf8ff" for char in pdf_text)
    assert not re.search(r"(?:--|[—–])\s*$", pdf_text, flags=re.MULTILINE)
    assert len(package["cover_letter"]["paragraphs"]) == 3
    cover_text = Path(package["cover_letter_text_path"]).read_text(encoding="utf-8")
    assert cover_text.split("\n\n")[1:4] == package["cover_letter"]["paragraphs"]
    assert "**Date**: 2026-04-08" in Path(package["cover_letter_md_path"]).read_text(encoding="utf-8")
    assert "2026-04-08" in cover_pdf_text
    assert package["preflight"]["passed"]
    assert package["quality_report"]["integrity_linter"]["passed"]
    typography = package["quality_report"]["typography_audit"]
    assert typography["final_page_count"] == 1
    assert typography["cover_letter_word_count"] > 0
    assert typography["cl_within_target_range"] is False
    assert Path(package["output_docx"]).name == f"{role}.docx"
    assert Path(package["output_pdf"]).name == f"{role}.pdf"
    assert not package["quality_report"]["ats_readability"]["ats_readability_flags"]


def test_chinese_resume_docx_pdf_preserves_evidence(tmp_path: Path) -> None:
    if find_libreoffice() is None or find_tectonic() is None:
        pytest.skip("Chinese PDF test needs LibreOffice and Tectonic")

    class _ChineseModel:
        available = True
        model_name = "synthetic_test_model"

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            if response_model.__name__ == "JDAnalysis":
                return response_model(role_type="ai_research", must_haves=["Python"])
            if response_model.__name__ == "GeneratedTailoring":
                return response_model.model_validate({
                    "profile": "", "profile_evidence_ids": [],
                    "sections": [{"type": "projects", "title": "Projects", "items": [{
                        "source_item_id": "p:3:body",
                        "bullets": [{"text": "使用 Python 完成模型评估，将错误率降低 5.2%。",
                                     "evidence_ids": ["p:3:body:bullet:0"]}],
                    }]}], "skills": {}, "evidence_gaps": [], "strategy": {},
                })
            return response_model.model_validate({
                "salutation": "Dear Hiring Team,",
                "paragraphs": [
                    "I am interested in this technical role and bring verified Python experience relevant to its stated engineering needs. " * 3,
                    "My documented work includes evaluating models, improving error by 5.2%, preserving reproducibility, and building reliable technical workflows. " * 9,
                    "I value careful engineering and collaborative problem solving. I welcome a technical discussion about the role and its priorities. " * 4,
                ],
                "closing": "Sincerely, Candidate",
                "evidence_ids": ["p:3:body:bullet:0"], "evidence_gaps": [],
            })

    source = tmp_path / "source.docx"
    document = Document()
    for line in ("Candidate", "candidate@example.com", "PROJECTS", "Model Evaluation",
                 "Used Python to evaluate models and reduced error by 5.2%."):
        document.add_paragraph(line)
    document.save(source)
    service = ApplicationService(Settings(output_dir=str(tmp_path)), provider=_ChineseModel())

    package = asyncio.run(service.generate_docx_application_package(
        str(source), "AI Lab Python evaluation", str(tmp_path / "chinese.docx"),
        "Example", resume_language="zh_CN",
    ))
    _, text = extract_pdf_text(package["output_pdf"])

    assert "使用 Python" in text
    assert "5.2%" in text
    assert package["resume_language"] == "zh_CN"
    assert package["quality_report"]["pages"]["output"] == 1