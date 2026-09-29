from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_TRAILING_FILLER = re.compile(r"[\s\-‐‑‒–—\u2010-\u2015\u2212]+$")
_TRAILING_FILLER_WITH_PUNCTUATION = re.compile(
    r"[\s\-‐‑‒–—\u2010-\u2015\u2212.]+$"
)
_TERMINAL_PUNCTUATION = re.compile(r"[.!?。；;！？]+$")
_CJK_TEXT = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff]")


@lru_cache(maxsize=1)
def _canonical_tech_terms() -> tuple[re.Pattern[str], dict[str, str]]:
    terms = json.loads(Path(__file__).with_name("technology_terms.json").read_text(encoding="utf-8"))
    canonical = {term.casefold(): term for term in reversed(terms)}
    pattern = re.compile(
        r"(?<![\w+])(?:" + "|".join(
            re.escape(term) for term in sorted(canonical.values(), key=len, reverse=True)
        ) + r")(?![\w+])",
        re.IGNORECASE,
    )
    return pattern, canonical


def normalize_technology_casing(text: str, source_text: str) -> str:
    if not text or not source_text:
        return text
    pattern, canonical = _canonical_tech_terms()

    def replace(match: re.Match[str]) -> str:
        term = match.group()
        supported = re.search(
            r"(?<![\w+])" + re.escape(term) + r"(?![\w+])",
            source_text, flags=re.IGNORECASE,
        )
        return canonical[term.casefold()] if supported else term

    return pattern.sub(replace, text)


def strip_trailing_fillers(text: str) -> str:
    cleaned = _TRAILING_FILLER.sub("", text.strip())
    return _TRAILING_FILLER_WITH_PUNCTUATION.sub("", cleaned).rstrip()


def normalize_sentence_ending(text: str, language: str = "en") -> str:
    cleaned = strip_trailing_fillers(text)
    if not cleaned:
        return cleaned
    if language == "zh_CN" or _CJK_TEXT.search(cleaned):
        return _TERMINAL_PUNCTUATION.sub("", cleaned).rstrip() + "。"
    return _TERMINAL_PUNCTUATION.sub("", cleaned).rstrip() + "."
