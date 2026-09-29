from pathlib import Path

import pytest

from career_resume_skill import latex
from career_resume_skill.latex import (
    compile_latex,
    escape_latex,
    find_compiler,
    prune_low_priority_resume,
    render_template,
)
from career_resume_skill.quality import extract_pdf_text


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


def test_render_cover_letter_escapes_content_and_requires_date(tmp_path: Path) -> None:
    output = render_template(
        "cover_letter",
        {
            "name": "A&B",
            "contact": {"email": "a_b@example.com"},
            "date": "2026-09-24",
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
        "name": "Candidate", "contact": contact, "date": "2026-09-26",
        "company_name": "Acme & Co", "salutation": "Dear Hiring Team,",
        "paragraphs": ["My Python experience fits this role.",
                       "I improved accuracy by 5.2% using verified Python tools.",
                       "I would welcome a technical discussion."],
        "closing": "Sincerely, Candidate",
    }, tmp_path / "cover.tex")
    rendered_cover = cover.read_text(encoding="utf-8")

    assert r"Acme \& Co" in rendered_cover
    assert r"{\bfseries Date:}" in rendered_cover
    assert r"{\bfseries To:} Hiring Team" in rendered_cover
    for tex in (resume, cover):
        pdf = compile_latex(tex, page_limit=1)
        pages, text = extract_pdf_text(pdf["pdf_path"])
        assert pages == 1
        assert "5.2%" in text
        if tex == resume:
            assert "10⁻⁶" in text
            assert "1.2μs" in text
