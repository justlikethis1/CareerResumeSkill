from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .analysis import build_evidence_index
from .models import MasterCV

_METRIC_RE = re.compile(
    r"(?<![\w])"
    r"(?:sub\s*[-‐‑‒–—]\s*)?[+-]?"
    r"(?:\d+[²³¹⁰-⁹\u207a\u207b]+\d*|\d+(?:[.,]\d+)*)"
    r"(?:[eE][+-]?\d+)?"
    r"(?:[kKmMgG])?"
    r"(?:\s*[-‐‑‒–—]?\s*bits?)?"
    r"(?:[×*]\s*10(?:[²³¹⁰-⁹\u207a\u207b\d+-]+)?)?"
    r"(?:\s?(?:%|x|ms|us|μs|ns|s|min|h|GB|TB|MB|KB|MHz|GHz|μm|um|°|QPS|RPS|TPS|IOPS|bps|kbps|Mbps|Gbps|tokens/s))?"
    r"(?![\w])",
    re.IGNORECASE,
)
_TECHNOLOGIES = json.loads(Path(__file__).with_name("technology_terms.json").read_text(encoding="utf-8"))
_HALLUCINATION_BLACKLIST = tuple(
    json.loads(
        Path(__file__).with_name("hallucination_blacklist.json").read_text(encoding="utf-8")
    )
)


def _technology_term_pattern(term: str) -> str:
    parts = re.split(r"[\s-]+", term)
    return r"[\s\-‐‑‒–—−]+".join(re.escape(part) for part in parts)


_TECH_RE = re.compile(
    r"(?<![\w+])(?:" + "|".join(
        _technology_term_pattern(term)
        for term in sorted(_TECHNOLOGIES, key=len, reverse=True)
    ) + r")(?![\w+])",
    re.IGNORECASE,
)
_RANDOM_FOREST_ABBREVIATION_RE = re.compile(
    r"(?<![\w])(?:XGBoost\s*/\s*RF|RF\s*/\s*XGBoost)(?![\w])",
    re.IGNORECASE,
)
_HALLUCINATION_PATTERNS = {
    term: re.compile(
        (
            r"(?<![A-Za-z0-9-])" + re.escape(term) + r"(?![A-Za-z0-9-])"
            if term == "Ray" else
            r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
        ),
        re.IGNORECASE,
    )
    for term in _HALLUCINATION_BLACKLIST
}


def extract_technologies(text: str) -> set[str]:
    technologies = {match.group(0).casefold() for match in _TECH_RE.finditer(text)}
    if _RANDOM_FOREST_ABBREVIATION_RE.search(text):
        technologies.add("random forest")
    return technologies


def normalize_technology(technology: str) -> str:
    compact = re.sub(r"[\s\-‐‑‒–—−]+", "", technology).casefold()
    return {
        "llmdrivenreasoning": "llmreasoning",
        "multiagentsystems": "multiagent",
    }.get(compact, compact)


def unsupported_technology_terms(source_text: str, generated_text: str) -> set[str]:
    source_technologies = {
        normalize_technology(term) for term in extract_technologies(source_text)
    }
    return {
        term.casefold()
        for term in extract_technologies(generated_text)
        if normalize_technology(term) not in source_technologies
    }


def extract_hallucination_blacklist_terms(text: str) -> set[str]:
    return {
        term.casefold()
        for term, pattern in _HALLUCINATION_PATTERNS.items()
        if pattern.search(text)
    }


def extract_metrics(text: str) -> set[str]:
    return {match.group(0) for match in _METRIC_RE.finditer(text)}


def normalize_metric(metric: str) -> str:
    compact = re.sub(r"\s+", "", metric)
    normalized = re.sub(r"[‐‑‒–—−]", "-", compact)
    return re.sub(r"(?<=\d)-(?=bits?\b)", "", normalized, flags=re.IGNORECASE)


def build_fact_cards(master_cv: dict[str, Any] | MasterCV) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    if isinstance(master_cv, dict):
        cv_source = {
            key: master_cv[key]
            for key in ("name", "contact", "profile", "sections", "skills")
            if key in master_cv
        }
    else:
        cv_source = master_cv
    for record in build_evidence_index(cv_source):
        text = record.text.strip()
        if not text:
            continue
        metrics = list(dict.fromkeys(match.group(0) for match in _METRIC_RE.finditer(text)))
        technologies = list(dict.fromkeys(match.group(0) for match in _TECH_RE.finditer(text)))
        cards.append(
            {
                "fact_id": f"fact:{record.evidence_id}",
                "evidence_id": record.evidence_id,
                "kind": record.kind,
                "section_type": record.section_type,
                "text": text,
                "technologies": technologies,
                "verified_metrics": metrics,
            }
        )
    return cards
