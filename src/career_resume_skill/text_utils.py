from __future__ import annotations

import re

_TRAILING_FILLER = re.compile(r"[\s\-‐‑‒–—\u2010-\u2015\u2212]+$")
_TRAILING_FILLER_WITH_PUNCTUATION = re.compile(
    r"[\s\-‐‑‒–—\u2010-\u2015\u2212.]+$"
)
_TERMINAL_PUNCTUATION = re.compile(r"[.!?。；;！？]+$")
_CJK_TEXT = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff]")


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
