import json
from pathlib import Path

from career_resume_skill.critic import CoverLetterCritic, DocxCritic, TextContentCritic
from career_resume_skill.harness.assertions import GoldenTestCase, evaluate_report
from career_resume_skill.harness.eval_runner import (
    evaluate_report_file,
    load_cases,
    write_scorecard,
)


def test_cover_letter_critic_detects_dangling_opening_and_repetition() -> None:
    result = CoverLetterCritic.audit([
        "As an engineer, I build measurable systems.",
        "I build measurable systems for reliable delivery.",
        "I build measurable systems for reliable delivery.",
    ])

    assert result.passed is False
    assert any("cross_paragraph_repetition" in issue for issue in result.issues)


def test_cover_letter_critic_detects_dangling_candidate_opening() -> None:
    result = CoverLetterCritic.audit([
        "An AI systems engineer candidate, I build reproducible workflows.",
        "Evidence supports this work with measured outcomes.",
        "I welcome a technical discussion.",
    ])

    assert result.passed is False
    assert any("dangling_opening" in issue for issue in result.issues)


def test_cover_letter_critic_ngram_size_is_configurable() -> None:
    paragraphs = [
        "I build reliable inference pipelines for model serving.",
        "I build reliable inference pipelines for model serving.",
    ]

    assert CoverLetterCritic.audit(paragraphs, ngram_size=6).passed is False
    assert CoverLetterCritic.audit(paragraphs, ngram_size=9).passed is True


def test_cover_letter_critic_flags_buzzwords_and_long_sentences_without_substring_matches() -> None:
    result = CoverLetterCritic.audit([
        "I am passionate about technical delivery and excited by this role.",
        "I measured pipeline throughput and reduced latency using verified evidence across several production systems with careful engineering decisions and reproducible validation under changing workload conditions.",
        "I welcome a technical discussion about this work.",
    ])
    assert any("excessive_buzzwords: passionate, excited" in issue for issue in result.issues)
    long_sentence = " ".join(["Measured pipeline throughput"] * 10) + "."
    assert any("low_readability:" in issue for issue in CoverLetterCritic.audit([long_sentence]).issues)
    assert CoverLetterCritic.audit(["I expressed the result."]).passed


def test_docx_critic_detects_trailing_fillers() -> None:
    result = DocxCritic.audit_bullets(["Measured latency.", "Built a pipeline.-----"])

    assert result.passed is False
    assert "trailing_filler" in result.issues[0]
    assert DocxCritic.audit_text("Built a pipeline.-----").passed is False


def test_text_content_critic_detects_resume_content_problems() -> None:
    result = TextContentCritic.audit_resume([
        "Built a Python pipeline.",
        "Built a Python pipeline.",
        "- Added evaluation.",
    ])

    assert result.passed is False
    assert any("duplicate_bullet" in issue for issue in result.issues)
    assert any("markdown_bullet_prefix" in issue for issue in result.issues)


def test_text_content_critic_detects_cover_letter_boilerplate() -> None:
    result = TextContentCritic.audit_cover([
        "I am writing to apply for this role.",
        "Evidence-backed work supports the role.",
        "I welcome a technical discussion.",
    ])

    assert result.passed is False
    assert "boilerplate_opening" in result.issues


def test_harness_evaluates_report_and_writes_scorecard(tmp_path: Path) -> None:
    report_path = tmp_path / "application-report.json"
    report_path.write_text(json.dumps({
        "tailored_cv": {"sections": [], "profile": "Measured sub-10ms latency."},
        "cover_letter": {"paragraphs": ["Evidence-backed work."]},
        "quality_report": {"pages": {"output": 1}, "integrity_linter": {"passed": True}},
        "ats_report": {"score": 88},
    }), encoding="utf-8")
    case = GoldenTestCase(id="case-1", expected_metrics=["sub-10ms"], min_ats_score=80)

    result = evaluate_report_file(report_path, case=case)
    scorecard = write_scorecard([result], tmp_path / "scorecard.md")

    assert result.passed is True
    assert scorecard.read_text(encoding="utf-8").startswith("# Application Evaluation Scorecard")


def test_harness_rejects_forbidden_terms() -> None:
    result = evaluate_report(
        {
            "tailored_cv": {"profile": "Used PyTorch."},
            "cover_letter": {"paragraphs": []},
            "ats_report": {"score": 90},
        },
        GoldenTestCase(id="case-2", forbidden_terms=["PyTorch"]),
    )

    assert result.passed is False
    assert result.forbidden_leakage_detected is True


def test_harness_requires_page_and_integrity_results() -> None:
    result = evaluate_report(
        {"tailored_cv": {}, "cover_letter": {}, "ats_report": {}},
        GoldenTestCase(id="missing-report"),
    )

    assert result.passed is False
    assert {"page_budget", "integrity"} <= set(result.issues)


def test_harness_loads_multiple_cases(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [{"id": "case-a", "expected_pages": 1}]}), encoding="utf-8")

    cases = load_cases(path)

    assert cases["case-a"].expected_pages == 1