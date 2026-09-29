from __future__ import annotations

import re
from collections.abc import Iterable

from .cl_critic import CriticResult


class TextContentCritic:
    """Audit candidate-facing resume text without rewriting or inventing content."""

    _MARKDOWN_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
    _BOILERPLATE = re.compile(
        r"\b(?:i am applying|i am writing to apply|i am interested in applying)\b",
        re.IGNORECASE,
    )

    @classmethod
    def audit_resume(cls, bullets: Iterable[str]) -> CriticResult:
        issues: list[str] = []
        seen: dict[str, int] = {}
        for index, raw_bullet in enumerate(bullets):
            bullet = raw_bullet.strip()
            normalized = re.sub(r"\s+", " ", bullet.casefold())
            if normalized in seen:
                issues.append(f"duplicate_bullet: {seen[normalized]} and {index}")
            else:
                seen[normalized] = index
            if cls._MARKDOWN_PREFIX.search(raw_bullet):
                issues.append(f"markdown_bullet_prefix: {index}")
            if raw_bullet != raw_bullet.strip() or re.search(r"\s{2,}", raw_bullet):
                issues.append(f"abnormal_whitespace: {index}")
            if bullet and not bullet.endswith((".", "。")):
                issues.append(f"invalid_sentence_ending: {index}")
        return CriticResult(not issues, tuple(dict.fromkeys(issues)))

    @classmethod
    def audit_cover(cls, paragraphs: Iterable[str]) -> CriticResult:
        values = [paragraph.strip() for paragraph in paragraphs]
        issues: list[str] = []
        if len(values) != 3:
            issues.append(f"paragraph_count: expected 3, got {len(values)}")
        if any(cls._BOILERPLATE.search(paragraph) for paragraph in values):
            issues.append("boilerplate_opening")
        if any(cls._MARKDOWN_PREFIX.search(paragraph) for paragraph in values):
            issues.append("markdown_in_prose")
        if any(not paragraph or re.search(r"\s{2,}", paragraph) for paragraph in values):
            issues.append("empty_or_abnormal_paragraph")
        return CriticResult(not issues, tuple(dict.fromkeys(issues)))