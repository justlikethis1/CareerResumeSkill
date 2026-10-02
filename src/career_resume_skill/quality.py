from __future__ import annotations

import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .docx_engine import calculate_docx_layout_budget, inspect_docx
from .docx_profile import import_docx_as_master_cv
from .facts import (
    extract_hallucination_blacklist_terms,
    extract_metrics,
    normalize_metric,
    unsupported_technology_terms,
)
from .typography import estimate_string_width

_ILLEGAL_TRAILING_DASH = re.compile(
    r"(?:[-‐‑‒–—\u2010-\u2015\u2212]+\s*\.?|\.?\s*[-‐‑‒–—\u2010-\u2015\u2212]+)$"
)


def extract_pdf_text(pdf_path: str | Path) -> tuple[int, str]:
    reader = PdfReader(str(Path(pdf_path).expanduser().resolve()))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return len(reader.pages), "\n".join(
        _strip_pdf_extraction_dash_artifact(line) for line in text.splitlines()
    )


def audit_docx_health(docx_path: str | Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="career-audit-") as resources:
        document = inspect_docx(docx_path, resources)
        layout = calculate_docx_layout_budget(docx_path, resources)
    paragraphs = {entry["paragraph_id"]: entry for entry in layout["paragraphs"]}
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    table_paragraphs = [
        paragraph for paragraph in document.paragraphs if paragraph.table_path and paragraph.text.strip()
    ]
    word_capacity = sum(
        entry["estimated_source_lines"] * max(1, int(
            entry["available_width_pt"] / max(1, estimate_string_width(
                "average ", entry["font_name"], entry["font_size_pt"], entry["bold"]
            ))
        ))
        for entry in layout["paragraphs"]
    )
    return {
        "estimated_current_lines": sum(
            entry["estimated_source_lines"] for entry in layout["paragraphs"]
        ),
        "estimated_current_line_word_capacity": word_capacity,
        "private_use_codepoints": sorted({
            f"U+{ord(char):04X}" for char in text if "\ue000" <= char <= "\uf8ff"
        }),
        "table_health": {
            "paragraphs": len(table_paragraphs),
            "nested_paragraphs": sum(len(paragraph.table_path) > 3 for paragraph in table_paragraphs),
            "widths_unresolved": [
                paragraph.node_id for paragraph in table_paragraphs
                if paragraphs.get(paragraph.node_id, {}).get("table_cell_width_twips") is None
            ],
        },
        "method": "Pillow estimate for existing paragraphs, not a full-page Word layout guarantee",
    }


def lint_output_integrity(
    source_evidence_text: str,
    output_text: str,
    page_count: int,
    *,
    expected_pages: int = 1,
    bullet_texts: list[str] | None = None,
    source_technology_text: str | None = None,
) -> dict[str, Any]:
    source_metrics = extract_metrics(source_evidence_text)
    output_metrics = {normalize_metric(metric) for metric in extract_metrics(output_text)}
    missing_metrics = sorted(
        (
            metric for metric in source_metrics
            if _is_primary_metric(metric)
            and normalize_metric(metric) not in output_metrics
        ),
        key=str.casefold,
    )
    technology_source = source_technology_text or source_evidence_text
    source_blacklist = extract_hallucination_blacklist_terms(technology_source)
    output_blacklist = extract_hallucination_blacklist_terms(output_text)
    unauthorized_blacklist = sorted(output_blacklist - source_blacklist)
    unauthorized_technologies = sorted(
        unsupported_technology_terms(technology_source, output_text)
        - set(unauthorized_blacklist)
    )
    private_use = sorted(
        {character for character in output_text if "\ue000" <= character <= "\uf8ff"}
    )
    punctuation_text = output_text if bullet_texts is None else ""
    if bullet_texts is None:
        punctuation_text = _normalize_pdf_line_break_hyphens(punctuation_text)
    checked_bullets = bullet_texts if bullet_texts is not None else punctuation_text.splitlines()
    trailing_dashes = [
        bullet.strip()
        for bullet in checked_bullets
        if _ILLEGAL_TRAILING_DASH.search(bullet.strip())
    ]
    trailing_dashes = list(dict.fromkeys(trailing_dashes))
    checks = {
        "page_budget": {"passed": page_count == expected_pages, "actual": page_count, "expected": expected_pages},
        "key_metric_invariance": {"passed": not missing_metrics, "missing": missing_metrics},
        "technology_provenance": {
            "checked": bool(source_evidence_text.strip()),
            "passed": not unauthorized_technologies,
            "unauthorized": unauthorized_technologies,
        },
        "hallucination_blacklist": {
            "checked": bool(source_evidence_text.strip()),
            "passed": not unauthorized_blacklist,
            "unauthorized": unauthorized_blacklist,
        },
        "punctuation": {"passed": not trailing_dashes, "trailing_dash_bullets": trailing_dashes},
        "glyph_hygiene": {"passed": not private_use, "private_use_codepoints": [f"U+{ord(c):04X}" for c in private_use]},
    }
    return {"passed": all(check["passed"] for check in checks.values()), "checks": checks}


def lint_payload_bullets(
    source_evidence_text: str, bullet_texts: list[str], *, language: str = "en"
) -> dict[str, Any]:
    text = "\n".join(bullet_texts)
    output_metrics = {normalize_metric(metric) for metric in extract_metrics(text)}
    metric_missing = sorted(
        (metric for metric in extract_metrics(source_evidence_text) if _is_primary_metric(metric)
         if normalize_metric(metric) not in output_metrics),
        key=str.casefold,
    )
    unauthorized_blacklist = sorted(
        extract_hallucination_blacklist_terms(text)
        - extract_hallucination_blacklist_terms(source_evidence_text)
    )
    unauthorized_technologies = sorted(
        unsupported_technology_terms(source_evidence_text, text)
        - set(unauthorized_blacklist)
    )
    valid_sentence_endings = ("。",) if language == "zh_CN" else (".",)
    invalid = [
        index for index, bullet in enumerate(bullet_texts)
        if not bullet.endswith(valid_sentence_endings)
        or bullet.endswith("..")
        or bullet != bullet.strip()
        or re.search(r"\s{2,}", bullet)
        or _ILLEGAL_TRAILING_DASH.search(bullet)
    ]
    glyphs = sorted({f"U+{ord(char):04X}" for char in text if "\ue000" <= char <= "\uf8ff"})
    return {
        "passed": not (
            metric_missing or unauthorized_technologies or unauthorized_blacklist or invalid or glyphs
        ),
        "missing_metrics": metric_missing,
        "unauthorized_technologies": unauthorized_technologies,
        "blacklisted_terms": unauthorized_blacklist,
        "invalid_bullet_indices": invalid,
        "private_use_codepoints": glyphs,
    }


def _is_primary_metric(metric: str) -> bool:
    normalized = normalize_metric(metric)
    if re.search(r"(?:μm|um|°|±)", normalized, re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"(?:%|sub\s*[-‐‑‒–—]?\s*\d|\b(?:ms|us|μs|ns|s|min|h|QPS|RPS|TPS|IOPS|bps|Mbps|Gbps|bits?)\b|"
            r"\b(?:GB|TB|MB|KB)\b|\d[²³¹⁰-⁹]+|\d+[eE][+-]?\d+)",
            normalized,
            re.IGNORECASE,
        )
    )


_OPERATIONAL_COUNT_RE = re.compile(
    r"\b(?P<count>\d[\d,]*)(?:\s+(?:supplier|customer|support|payment))?\s+"
    r"(?:invoices?|cases?|tickets?|orders?|transactions?|customers?)\b",
    re.IGNORECASE,
)


def _operational_counts(text: str) -> set[str]:
    return {normalize_metric(match.group("count")) for match in _OPERATIONAL_COUNT_RE.finditer(text)}


def _has_operational_count(text: str) -> bool:
    return bool(_OPERATIONAL_COUNT_RE.search(text))


def check_linear_text_stream(
    source_items: list[dict[str, Any]], pdf_text: str, bullet_texts: list[str] | None = None
) -> dict[str, Any]:
    def normalize(text: str) -> str:
        text = re.sub(r"(?<=[A-Za-z])(?=\d{2}[./-](?:19|20)\d{2}\b)", " ", text)
        return " ".join(re.findall(r"\w+", text.casefold()))

    lines = [normalize(line) for line in pdf_text.splitlines() if normalize(line)]
    stream = " ".join(lines)
    flags: list[dict[str, Any]] = []
    cursor = 0
    for index, item in enumerate(source_items):
        title = normalize(item.get("title", ""))
        if not title:
            continue
        title_pattern = rf"(?<!\w){re.escape(title)}(?!\w)"
        match = re.search(title_pattern, stream[cursor:])
        if match:
            position = cursor + match.start()
            end_position = cursor + match.end()
        else:
            earlier_match = re.search(title_pattern, stream)
            position = earlier_match.start() if earlier_match else -1
            end_position = earlier_match.end() if earlier_match else -1
        if position < 0:
            flags.append({"code": "missing_item_title", "item_index": index})
            continue
        if position < cursor:
            flags.append({"code": "item_out_of_order", "item_index": index})
        cursor = max(cursor, end_position)
        offset = 0
        title_line = None
        for number, line in enumerate(lines):
            if offset <= position < offset + len(line) + 1:
                title_line = number
                break
            offset += len(line) + 1
        for field in ("organization", "dates"):
            value = normalize(item.get(field, ""))
            if not value:
                continue
            nearby = (
                title_line is not None and any(
                    value in line for line in lines[max(0, title_line - 1):title_line + 3]
                )
            )
            if not nearby:
                flags.append({"code": f"{field}_not_near_title", "item_index": index})
    for index, bullet in enumerate(bullet_texts or []):
        if normalize(bullet) not in stream:
            flags.append({"code": "bullet_not_contiguous", "bullet_index": index})
    return {
        "method": "pypdf extracted text order heuristic; not a Workday/Taleo compatibility guarantee",
        "ats_readability_flags": flags,
    }


def document_quality_report(
    source_docx: str | Path,
    output_docx: str | Path,
    source_pdf: str | Path,
    output_pdf: str | Path,
    replacement_count: int,
    bullet_texts: list[str] | None = None,
) -> dict[str, Any]:
    source_docx_text = _docx_text(source_docx)
    output_docx_text = _docx_text(output_docx)
    source_pages, source_pdf_text = extract_pdf_text(source_pdf)
    output_pages, output_pdf_text = extract_pdf_text(output_pdf)
    output_visual = pdf_visual_metrics(output_pdf)
    source_pdf_metrics = _text_metrics(source_pdf_text, normalize_pdf_artifacts=True)
    output_pdf_metrics = _text_metrics(output_pdf_text, normalize_pdf_artifacts=True)
    docx_metrics = {
        "source": _text_metrics(source_docx_text),
        "output": _text_metrics(output_docx_text),
    }
    source_cv = import_docx_as_master_cv(source_docx)["master_cv"]
    source_items = [
        item for section in source_cv["sections"] for item in section["items"]
    ]
    return {
        "replacement_count": replacement_count,
        "pages": {"source": source_pages, "output": output_pages},
        "docx": docx_metrics,
        "pdf": {"source": source_pdf_metrics, "output": output_pdf_metrics},
        "visual_layout": output_visual,
        "ats_readability": check_linear_text_stream(source_items, output_pdf_text, bullet_texts),
        "diagnosis": {
            "docx_private_bullet_added": (
                docx_metrics["output"]["private_bullet"]
                > docx_metrics["source"]["private_bullet"]
            ),
            "pdf_private_bullet_delta": (
                output_pdf_metrics["private_bullet"] - source_pdf_metrics["private_bullet"]
            ),
            "pdf_hyphen_space_hyphen_delta": (
                output_pdf_metrics["hyphen_space_hyphen"]
                - source_pdf_metrics["hyphen_space_hyphen"]
            ),
            "duplicate_nonempty_paragraph_delta": (
                output_pdf_metrics["duplicate_nonempty_lines"]
                - source_pdf_metrics["duplicate_nonempty_lines"]
            ),
                "page_count_exceeded": output_pages > 1,
                "page_reduced": output_pages < source_pages,
                "page_count_changed": output_pages != source_pages,
        },
    }


def pdf_visual_metrics(pdf_path: str | Path) -> dict[str, Any]:
    reader = PdfReader(str(Path(pdf_path).expanduser().resolve()))
    page_metrics: list[dict[str, Any]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        height = float(page.mediabox.height)
        text_y: list[float] = []

        def visit_text(
            text: str,
            cm: Any,
            text_matrix: Any,
            _font: Any,
            _size: Any,
            page_text_y: list[float] = text_y,
        ) -> None:
            if text.strip() and len(cm) > 5 and len(text_matrix) > 5:
                page_text_y.append(
                    float(text_matrix[4] * cm[1] + text_matrix[5] * cm[3] + cm[5])
                )

        page.extract_text(visitor_text=visit_text)
        bottommost = min(text_y) if text_y else None
        whitespace = max(0.0, min(1.0, bottommost / height)) if bottommost is not None and height else None
        page_metrics.append(
            {
                "page": page_number,
                "height_pt": round(height, 2),
                "bottommost_text_y_pt": round(bottommost, 2) if bottommost is not None else None,
                "estimated_bottom_whitespace_ratio": round(whitespace, 4) if whitespace is not None else None,
                "within_3_to_10_percent_target": (
                    0.03 <= whitespace <= 0.10 if whitespace is not None else None
                ),
            }
        )
    return {
        "method": "pypdf combined text/graphics-matrix estimate; visual heuristic, not pixel-accurate rendering",
        "pages": page_metrics,
    }


def _docx_text(path: str | Path) -> str:
    report = inspect_docx(path)
    return "\n".join(paragraph.text for paragraph in report.paragraphs)


def _text_metrics(text: str, *, normalize_pdf_artifacts: bool = False) -> dict[str, int]:
    lines = [
        (
            _strip_pdf_extraction_dash_artifact(line.strip())
            if normalize_pdf_artifacts else line.strip()
        )
        for line in text.splitlines()
        if line.strip()
    ]
    counts = Counter(lines)
    return {
        "characters": len(text),
        "private_bullet": text.count("\uf0b7"),
        "nonbreaking_hyphen": text.count("\u2011"),
        "soft_hyphen": text.count("\u00ad"),
        "hyphen_space_hyphen": len(re.findall(r"[-\u2011]\s+[-\u2011]", text)),
        "trailing_dash_lines": sum(
            bool(re.search(r"[-\u2010\u2011\u2013\u2014]{2,}\s*$", line))
            for line in lines
        ),
        "duplicate_nonempty_lines": sum(count - 1 for count in counts.values() if count > 1),
    }


def _strip_pdf_extraction_dash_artifact(line: str) -> str:
    """Remove repeated dashes emitted after terminal punctuation by PDF extraction."""
    return re.sub(
        r"(?<=[.!?。；;！？])\s*[-‐‑‒–—\u2010-\u2015\u2212]{2,}\s*$",
        "",
        line,
    ).rstrip()


def _normalize_pdf_line_break_hyphens(text: str) -> str:
    """Join words split by PDF line wrapping while preserving repeated dash artifacts."""
    return re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
