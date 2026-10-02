import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from career_resume_skill import latex
from career_resume_skill.latex import (
    PageLimitError,
    compile_latex,
    escape_latex,
    find_compiler,
    prune_low_priority_resume,
    render_template,
)
from career_resume_skill.quality import extract_pdf_text


def test_page_limit_error_exposes_structured_context() -> None:
    error = PageLimitError(2, 1, "log excerpt")

    assert error.to_dict() == {
        "error": "PageLimitError",
        "message": "Rendered PDF has 2 pages; limit is 1",
        "pages": 2,
        "limit": 1,
        "log": "log excerpt",
    }


def test_escape_latex_special_characters() -> None:
    assert escape_latex(r"C++ & A_B saved 38% for $5 #1 ^ ~") == (
        r"C++ \& A\_B saved 38\% for \$5 \#1 \textasciicircum{} \textasciitilde{}"
    )


def test_compiler_rejects_pdftex_only_environment(monkeypatch) -> None:
    monkeypatch.setattr(latex.shutil, "which", lambda name: "pdflatex" if name == "pdflatex" else None)
    monkeypatch.setattr(latex, "find_tectonic", lambda: None)

    with pytest.raises(RuntimeError, match="fontspec-compatible"):
        latex.find_compiler()

    monkeypatch.setattr(latex.shutil, "which", lambda name: name if name == "xelatex" else None)
    assert latex.find_compiler()[0] == "xelatex"


def test_render_resume_escapes_content(tmp_path: Path) -> None:
    output = render_template(
        "resume",
        {
            "name": "A&B",
            "contact": {"email": "a_b@example.com"},
            "profile": "Saved 38%",
            "sections": [],
            "skills": {},
        },
        tmp_path / "resume.tex",
    )
    rendered = output.read_text(encoding="utf-8")

    assert r"A\&B" in rendered
    assert r"a\_b@example.com" in rendered
    assert r"38\%" in rendered


def test_resume_variable_length_locations_keep_right_edge(tmp_path: Path) -> None:
    if shutil.which("pdftotext") is None:
        pytest.skip("PDF word bounding boxes need pdftotext")
    try:
        find_compiler()
    except RuntimeError:
        pytest.skip("No LaTeX compiler installed")
    tex = render_template("resume", {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "profile": "", "sections": [{"title": "Experience", "items": [{
            "title": "Analyst", "dates": "2025",
            "organization": "Very Long Research and Development Organization Serving Several Regions and Teams",
            "location": "Zhejiang, China", "bullets": [],
        }, {
            "title": "Engineer", "dates": "2026", "organization": "Research Institute",
            "location": "Jiaxing, Zhejiang, Peoples Republic of China", "bullets": [],
        }]}], "skills": {},
    }, tmp_path / "resume.tex")
    pdf = compile_latex(tex, page_limit=1)
    pages, text = extract_pdf_text(pdf["pdf_path"])
    bbox = subprocess.run(
        [shutil.which("pdftotext"), "-bbox", pdf["pdf_path"], "-"],
        capture_output=True, text=True, check=True,
    )
    words = [word for word in ET.fromstring(bbox.stdout.encode()).iter()
             if word.tag.endswith("word")]
    right_edges = [float(word.attrib["xMax"]) for word in words if word.text == "China"]

    assert pages == 1 and "extbf" not in text and "extit" not in text
    assert len(right_edges) == 2 and abs(right_edges[0] - right_edges[1]) < 2
    long_location_tail = next(word for word in words if word.text == "China" and
                              float(word.attrib["xMax"]) == right_edges[1])
    assert float(long_location_tail.attrib["xMin"]) > 350


def test_resume_omits_empty_organization_location_row(tmp_path: Path) -> None:
    try:
        find_compiler()
    except RuntimeError:
        pytest.skip("No LaTeX compiler installed")
    tex = render_template("resume", {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "profile": "", "sections": [{"title": "Projects", "items": [{
            "title": "Independent Project", "dates": "2026", "organization": "",
            "location": "", "bullets": ["Built a Python tool."],
        }]}], "skills": {},
    }, tmp_path / "resume.tex")
    rendered = tex.read_text(encoding="utf-8")
    assert r"\resumeSubheadingSingle{Independent Project}{2026}" in rendered
    pdf = compile_latex(tex, page_limit=1)
    positions: dict[str, float] = {}

    def collect(text, cm, tm, font, size):
        for label in ("Independent Project", "Built a Python tool"):
            if label in text:
                positions[label] = cm[5] + tm[5]

    PdfReader(pdf["pdf_path"]).pages[0].extract_text(visitor_text=collect)

    assert pdf["pages"] == 1
    assert len(positions) == 2
    assert 0 < positions["Independent Project"] - positions["Built a Python tool"] < 18


def test_resume_omits_empty_skill_groups_and_heading(tmp_path: Path) -> None:
    base = {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "profile": "", "sections": [],
    }
    mixed = render_template("resume", {
        **base, "skills": {"Tools": ["Python"], "Unused": [], "Methods": ""},
    }, tmp_path / "mixed.tex").read_text(encoding="utf-8")
    empty = render_template("resume", {
        **base, "skills": {"Unused": [], "Methods": ""},
    }, tmp_path / "empty.tex").read_text(encoding="utf-8")

    assert r"\resumeSection{Skills}" in mixed
    assert r"\textbf{Tools:} Python" in mixed
    assert "Unused:" not in mixed and "Methods:" not in mixed
    assert r"\resumeSection{Skills}" not in empty


def test_render_cover_letter_escapes_content_and_requires_date(tmp_path: Path) -> None:
    output = render_template(
        "cover_letter",
        {
            "name": "A&B",
            "contact": {"email": "a_b@example.com"},
            "date": "September 24, 2026",
            "recipient_title": "Hiring Committee",
            "company_name": "Example & Co",
            "subject_line": "RE: Application for AI Research - A&B",
            "salutation": "Dear Hiring Team,",
            "paragraphs": ["A&B 38%", "C++ and C_CUDA", "Motivation $5 #1"],
            "closing": "Sincerely",
        },
        tmp_path / "cover.tex",
    )
    rendered = output.read_text(encoding="utf-8")

    assert r"A\&B" in rendered
    assert r"38\%" in rendered
    assert r"C++ and C\_CUDA" in rendered
    assert r"Motivation \$5 \#1" in rendered


def test_cover_letter_renders_cjk_subject_without_missing_glyphs(tmp_path: Path) -> None:
    try:
        find_compiler()
    except RuntimeError:
        pytest.skip("No LaTeX compiler installed")
    tex = render_template("cover_letter", {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "date": "October 2, 2026", "recipient_title": "Hiring Committee",
        "company_name": "MiniMax", "subject_line": "RE: Application for 大模型推理研发实习生 - Candidate",
        "salutation": "Dear Hiring Team,",
        "paragraphs": ["Documented research.", "Built a Python evaluation workflow.", "Welcome a discussion."],
        "closing": "Sincerely",
    }, tmp_path / "cjk-cover.tex")
    try:
        pdf = compile_latex(tex, page_limit=1)
    except RuntimeError as error:
        if "CJK font unavailable" in str(error):
            pytest.skip("No CJK font installed")
        raise
    pages, text = extract_pdf_text(pdf["pdf_path"])

    assert pages == 1
    assert "大模型推理研发实习生" in text
    assert "Missing character" not in pdf["log"]


def test_resume_renders_cjk_candidate_and_bullet_without_missing_glyphs(tmp_path: Path) -> None:
    try:
        find_compiler()
    except RuntimeError:
        pytest.skip("No LaTeX compiler installed")
    tex = render_template("resume", {
        "name": "候选人", "contact": {"email": "candidate@example.com", "location": "香港"},
        "profile": "具备有来源的 Python 模型评估经验。",
        "sections": [{"title": "项目经历", "items": [{
            "title": "模型评估", "dates": "2025", "organization": "研究团队", "location": "香港",
            "bullets": ["使用 Python 完成模型评估。"],
        }]}], "skills": {},
    }, tmp_path / "cjk-resume.tex")
    try:
        pdf = compile_latex(tex, page_limit=1)
    except RuntimeError as error:
        if "CJK font unavailable" in str(error):
            pytest.skip("No CJK font installed")
        raise
    pages, text = extract_pdf_text(pdf["pdf_path"])

    assert pages == 1
    assert "候选人" in text and "使用 Python 完成模型评估" in text
    assert "Missing character" not in pdf["log"]


def test_compile_rejects_missing_font_glyph_instead_of_silent_pdf(tmp_path: Path) -> None:
    try:
        find_compiler()
    except RuntimeError:
        pytest.skip("No LaTeX compiler installed")
    tex = render_template("cover_letter", {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "date": "October 2, 2026", "recipient_title": "Hiring Committee",
        "company_name": "Example", "subject_line": "Application for 🦄 Research",
        "salutation": "Dear Team,",
        "paragraphs": ["Documented research.", "Built a Python evaluation workflow.", "Welcome a discussion."],
        "closing": "Sincerely",
    }, tmp_path / "unsupported-glyph.tex")

    with pytest.raises(RuntimeError, match="missing glyphs"):
        compile_latex(tex, page_limit=1)


def test_page_budget_prunes_lowest_scored_bullet_first() -> None:
    content = {
        "sections": [
            {
                "items": [
                    {
                        "source_item_id": "high",
                        "bullets": ["High one", "High two"],
                        "evidence_ids": ["high:0", "high:1"],
                    },
                    {
                        "source_item_id": "low",
                        "bullets": ["Low one", "Low two"],
                        "evidence_ids": ["low:0", "low:1"],
                    },
                ]
            }
        ],
        "strategy": {"item_scores": {"high": 10, "low": 1}},
    }

    pruned, action = prune_low_priority_resume(content)

    assert pruned["sections"][0]["items"][0]["bullets"] == ["High one", "High two"]
    assert pruned["sections"][0]["items"][1]["bullets"] == ["Low one"]
    assert pruned["sections"][0]["items"][1]["evidence_ids"] == ["low:0"]
    assert action is not None and "low" in action


def test_prune_low_priority_resume_does_not_remove_primary_metric_bullets() -> None:
    content = {
        "sections": [{"items": [{
            "source_item_id": "only",
            "bullets": ["Measured sub-10ms latency.", "Built a Python pipeline."],
            "evidence_ids": ["only:0", "only:1"],
        }]}],
        "strategy": {"item_scores": {"only": 1}},
    }

    pruned, action = prune_low_priority_resume(content)

    assert pruned["sections"][0]["items"][0]["bullets"] == [
        "Measured sub-10ms latency.",
    ]
    assert action is not None


def test_prune_low_priority_resume_preserves_operational_case_count() -> None:
    content = {
        "sections": [{"items": [{
            "source_item_id": "support",
            "bullets": ["Resolved 95 customer cases.", "Documented team handovers."],
            "evidence_ids": ["support:0", "support:1"],
        }]}],
        "strategy": {"item_scores": {"support": 1}},
    }

    pruned, action = prune_low_priority_resume(content)

    assert pruned["sections"][0]["items"][0]["bullets"] == ["Resolved 95 customer cases."]
    assert action is not None and "Documented team handovers" in action


def test_prune_low_priority_resume_removes_non_metric_bullet_before_metric_tail() -> None:
    content = {
        "sections": [{"items": [{
            "source_item_id": "mixed",
            "bullets": ["Built a Python pipeline.", "Measured sub-10ms latency."],
            "evidence_ids": ["mixed:0", "mixed:1"],
        }]}],
        "strategy": {"item_scores": {"mixed": 1}},
    }

    pruned, action = prune_low_priority_resume(content)

    assert pruned["sections"][0]["items"][0]["bullets"] == [
        "Measured sub-10ms latency.",
    ]
    assert pruned["sections"][0]["items"][0]["evidence_ids"] == ["mixed:1"]
    assert action is not None and "Built a Python pipeline." in action


def test_compact_resume_retains_four_bullets_and_exposes_spacing_knobs(tmp_path: Path) -> None:
    content = {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "profile": "", "sections": [{"title": "Projects", "items": [{
            "title": "Pipeline", "organization": "Example", "dates": "2025", "location": "Remote",
            "bullets": ["First.", "Second.", "Third.", "Fourth 5.2%."],
        }]}], "skills": {},
    }
    for level in (0, 1, 2):
        tex = render_template("resume", content, tmp_path / f"resume-{level}.tex", compact=level)
        rendered = tex.read_text(encoding="utf-8")

        assert r"\resumeItem{Fourth 5.2\%.}" in rendered
        assert all(f"\\{macro}" in rendered for macro in (
            "resumeMargin", "resumeItemSep", "resumeSectionSep", "resumeLineSpread"
        ))


def test_business_letter_and_resume_compile_to_extractable_single_page(tmp_path: Path) -> None:
    try:
        find_compiler()
    except RuntimeError:
        pytest.skip("No LaTeX compiler installed")
    contact = {"email": "candidate@example.com", "phone": "+1 555 000 1111"}
    resume = render_template("resume", {
        "name": "Candidate", "contact": contact, "profile": "Python & C++ engineering.",
        "sections": [{"title": "Projects", "items": [{
            "title": "Pipeline", "dates": "2025", "organization": "Example", "location": "Remote",
            "bullets": ["Improved accuracy by 5.2% using Python; measured 10⁻⁶ error at 1.2μs."],
        }]}], "skills": {},
    }, tmp_path / "resume.tex")
    cover = render_template("cover_letter", {
        "name": "Candidate", "contact": contact, "date": "September 26, 2026",
        "recipient_title": "Hiring Committee", "subject_line": "RE: Application for Software Engineering - Candidate",
        "company_name": "Acme & Co", "salutation": "Dear Hiring Team,",
        "paragraphs": ["My Python experience fits this role.",
                       "I improved accuracy by 5.2% using verified Python tools.",
                       "I would welcome a technical discussion."],
        "closing": "Sincerely, Candidate",
    }, tmp_path / "cover.tex")
    rendered_cover = cover.read_text(encoding="utf-8")

    assert r"Acme \& Co" in rendered_cover
    assert r"{\bfseries Date:}" in rendered_cover
    assert r"{\bfseries To:} Hiring Committee" in rendered_cover
    assert r"RE: Application for Software Engineering - Candidate" in rendered_cover
    assert r"\csname textbf\endcsname{Candidate}" in rendered_cover
    for tex in (resume, cover):
        pdf = compile_latex(tex, page_limit=1)
        pages, text = extract_pdf_text(pdf["pdf_path"])
        assert pages == 1
        assert "5.2%" in text
        if tex == cover:
            assert "extbf" not in text
            assert "Candidate" in text
            positions: list[tuple[str, float, float]] = []

            def collect_signature(value, cm, tm, font, size, output=positions):
                if "Sincerely" in value or value.strip() == "Candidate":
                    output.append((value.strip(), tm[4] + cm[4], tm[5] + cm[5]))

            PdfReader(pdf["pdf_path"]).pages[0].extract_text(visitor_text=collect_signature)
            closing_x = next(x for value, x, y in positions if value.startswith("Sincerely"))
            signature_x = min(x for value, x, y in positions if value == "Candidate")
            assert abs(signature_x - closing_x) < 1
        if tex == resume:
            assert "10⁻⁶" in text
            assert "1.2μs" in text


def test_cover_letter_wraps_long_words_without_automatic_hyphenation(tmp_path: Path) -> None:
    try:
        find_compiler()
    except RuntimeError:
        pytest.skip("No LaTeX compiler installed")
    sentence = "Documented interoperability and reproducibility for teams."
    tex = render_template("cover_letter", {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "date": "October 2, 2026", "recipient_title": "Hiring Committee",
        "company_name": "Example", "subject_line": "RE: Application for Engineering",
        "salutation": "Dear Hiring Team,",
        "paragraphs": [" ".join([sentence] * count) for count in (9, 25, 11)],
        "closing": "Sincerely",
    }, tmp_path / "cover-letter.tex")
    pdf = compile_latex(tex, page_limit=1)
    pages, text = extract_pdf_text(pdf["pdf_path"])

    assert pages == 1
    assert "interoperability" in text
    assert "interoper-\nability" not in text
    assert "reproduci-\nbility" not in text
    assert "Overfull" not in pdf["log"]
