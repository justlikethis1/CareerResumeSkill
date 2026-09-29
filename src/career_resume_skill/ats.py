from __future__ import annotations

from typing import Any

from .analysis import REQUIREMENT_ALIASES, _contains, filter_atomic_requirements


def score_ats(jd_analysis: dict[str, Any], candidate_text: str) -> dict[str, Any]:
    hard_requirements, _ = filter_atomic_requirements(_unique(
        [
            *jd_analysis.get("must_haves", []),
            *jd_analysis.get("hard_skills", []),
        ]
    ))
    preferred, _ = filter_atomic_requirements(_unique(
        [
            *jd_analysis.get("nice_to_haves", []),
            *jd_analysis.get("ats_keywords", []),
        ]
    ))
    hard = _score_terms(hard_requirements, candidate_text)
    nice = _score_terms(preferred, candidate_text)
    hard_coverage = _percent(len(hard["matched"]), len(hard_requirements))
    preferred_coverage = _percent(len(nice["matched"]), len(preferred))
    composite = round(hard_coverage * 0.8 + preferred_coverage * 0.2)
    return {
        "score": composite,
        "interpretation": "heuristic keyword coverage; not a prediction of any proprietary ATS ranking",
        "hard_skill_coverage_percent": hard_coverage,
        "preferred_keyword_coverage_percent": preferred_coverage,
        "hard_requirements": hard,
        "preferred_keywords": nice,
        "warnings": [
            "ATS score is a transparent local keyword estimate, not a hiring probability."
        ],
    }


def _score_terms(terms: list[str], candidate_text: str) -> dict[str, Any]:
    exact: list[str] = []
    semantic: dict[str, list[str]] = {}
    missing: list[str] = []
    for term in terms:
        if _contains(candidate_text, term):
            exact.append(term)
            continue
        supporting = [
            alias for alias in REQUIREMENT_ALIASES.get(term, ()) if _contains(candidate_text, alias)
        ]
        if supporting:
            semantic[term] = supporting
        else:
            missing.append(term)
    return {
        "total": len(terms),
        "matched": exact + list(semantic),
        "exact_matches": exact,
        "semantic_matches": semantic,
        "missing": missing,
    }


def _unique(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _percent(numerator: int, denominator: int) -> int:
    return round(100 * numerator / denominator) if denominator else 0
