from __future__ import annotations

import re
from collections.abc import Iterable

from .cl_critic import CriticResult


class DocxCritic:
    """Audit extracted DOCX/PDF bullet text without changing source artifacts."""

    _TRAILING_FILLER = re.compile(r"(?:[-‐‑‒–—\u2010-\u2015\u2212]{2,})\s*$")

    @classmethod
    def audit_bullets(cls, bullets: Iterable[str]) -> CriticResult:
        issues = [
            f"trailing_filler: {bullet.strip()}"
            for bullet in bullets
            if cls._TRAILING_FILLER.search(bullet.strip())
        ]
        return CriticResult(not issues, tuple(dict.fromkeys(issues)))

    @classmethod
    def audit_text(cls, text: str) -> CriticResult:
        return cls.audit_bullets(text.splitlines())