from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from ..facts import extract_hallucination_blacklist_terms
from ..quality import extract_pdf_text


class TypographyLinter:
    """Hard delivery checks for extraction-visible typography artifacts."""

    _DASH_ARTIFACT = re.compile(r"[-‐‑‒–—\u2010-\u2015\u2212]{2,}\s*$")

    @classmethod
    def check_pdf_typography(cls, extracted_text: str) -> tuple[bool, list[str]]:
        violations = [
            f"line {line_number}: {line.strip()[-35:]}"
            for line_number, line in enumerate(extracted_text.splitlines(), start=1)
            if cls._DASH_ARTIFACT.search(line.strip())
        ]
        return not violations, violations


class GoldenTestCase(BaseModel):
    id: str
    expected_pages: int = 1
    expected_metrics: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    min_ats_score: int | None = None


class EvalHarnessReport(BaseModel):
    test_case_id: str
    page_count: int | None
    metric_retention_rate: float
    forbidden_leakage_detected: bool
    ats_score: int | None
    passed: bool
    checks: dict[str, bool]
    issues: list[str] = Field(default_factory=list)


def evaluate_report(report: dict[str, Any], case: GoldenTestCase) -> EvalHarnessReport:
    ats = report.get("ats_report", {})
    quality = report.get("quality_report", {})
    integrity = quality.get("integrity_linter") or ats.get("integrity_linter") or {}
    page_count = (
        quality.get("pages", {}).get("output")
        or quality.get("typography_audit", {}).get("final_page_count")
        or ats.get("parseability", {}).get("page_count")
    )
    if page_count is None and report.get("documents"):
        document_pages = [
            document.get("pages")
            for document in report["documents"].values()
            if isinstance(document, dict) and document.get("pages") is not None
        ]
        page_count = max(document_pages) if document_pages else None
    tailored = report.get("tailored_cv", {})
    visible_sections = [
        item.get("title", "")
        for section in tailored.get("sections", [])
        for item in section.get("items", [])
    ] + [
        bullet
        for section in tailored.get("sections", [])
        for item in section.get("items", [])
        for bullet in item.get("bullets", [])
    ]
    skills = [
        skill
        for values in tailored.get("skills", {}).values()
        for skill in (values if isinstance(values, list) else [values])
    ]
    text_parts = [
        str(tailored.get("profile", "")),
        *visible_sections,
        *skills,
        *report.get("cover_letter", {}).get("paragraphs", []),
    ]
    report_text = _extract_artifact_text(report)
    output_text = (report_text or " ".join(text_parts)).casefold()
    typography_passed, typography_issues = TypographyLinter.check_pdf_typography(report_text)
    retained = [metric for metric in case.expected_metrics if metric.casefold() in output_text]
    forbidden = {term for term in case.forbidden_terms if term.casefold() in output_text}
    forbidden.update(extract_hallucination_blacklist_terms(output_text))
    ats_score = ats.get("score")
    issues: list[str] = []
    metric_rate = len(retained) / len(case.expected_metrics) if case.expected_metrics else 1.0
    checks_result = {
        "page_budget": page_count == case.expected_pages,
        "metric_retention": metric_rate == 1.0,
        "forbidden_leakage": not forbidden,
        "integrity": bool(integrity) and bool(integrity.get("passed")),
        "critic": _critic_passed(report),
        "typography": typography_passed,
        "ats_threshold": case.min_ats_score is None or (
            ats_score is not None and ats_score >= case.min_ats_score
        ),
    }
    for name, passed in checks_result.items():
        if not passed:
            issues.append(name)
    issues.extend(typography_issues)
    return EvalHarnessReport(
        test_case_id=case.id,
        page_count=page_count,
        metric_retention_rate=metric_rate,
        forbidden_leakage_detected=bool(forbidden),
        ats_score=ats_score,
        passed=all(checks_result.values()),
        checks=checks_result,
        issues=issues,
    )


def _extract_artifact_text(report: dict[str, Any]) -> str:
    paths: list[str] = []
    if report.get("output_pdf"):
        paths.append(str(report["output_pdf"]))
    if report.get("documents"):
        paths.extend(
            str(document["pdf_path"])
            for document in report["documents"].values()
            if isinstance(document, dict) and document.get("pdf_path")
        )
    cover_pdf = report.get("cover_letter_pdf", {})
    if isinstance(cover_pdf, dict) and cover_pdf.get("pdf_path"):
        paths.append(str(cover_pdf["pdf_path"]))
    chunks: list[str] = []
    for path in dict.fromkeys(paths):
        try:
            _, text = extract_pdf_text(path)
        except (OSError, ValueError):
            continue
        chunks.append(text)
    return "\n".join(chunks)


def _critic_passed(report: dict[str, Any]) -> bool:
    quality = report.get("quality_report", {})
    ats = report.get("ats_report", {})
    critic_reports = [
        quality.get("cover_letter_critic"),
        quality.get("cover_letter_content_critic"),
        quality.get("docx_critic"),
        quality.get("resume_content_critic"),
        ats.get("cover_letter_critic"),
        ats.get("cover_letter_content_critic"),
        ats.get("resume_content_critic"),
    ]
    return all(
        critic is None or critic.get("passed", False)
        for critic in critic_reports
        if isinstance(critic, dict)
    )