from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class CriticResult:
    passed: bool
    issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "issues": list(self.issues)}


class CoverLetterCritic:
    """Detect deterministic grammar and distinctive cross-paragraph repetition issues."""

    DEFAULT_NGRAM_SIZE = 6
    FORBIDDEN_BUZZWORDS = (
        "passionate", "excited", "thrilled", "enthusiastic", "game-changing",
        "valuable asset", "testament", "delve", "pleased", "deeply honored",
        "synergy", "cutting-edge", "revolutionary", "heartfelt",
    )
    _DANGLING_OPENINGS = (
        re.compile(r"^(?:an?|the)\s+[^,]{2,80}\bcandidate\b[^,]*,\s*i\b", re.IGNORECASE),
        re.compile(r"^(?:an?|the)\s+[^,]{2,80}\bengineer\b[^,]*,\s*i\b", re.IGNORECASE),
    )

    @classmethod
    def audit(
        cls, paragraphs: Iterable[str], *, ngram_size: int = DEFAULT_NGRAM_SIZE
    ) -> CriticResult:
        if ngram_size < 2:
            raise ValueError("ngram_size must be at least 2")
        values = [paragraph.strip() for paragraph in paragraphs if paragraph.strip()]
        issues: list[str] = []
        body = values[1:] if values and values[0].casefold().startswith("dear ") else values
        if body and any(pattern.search(body[0]) for pattern in cls._DANGLING_OPENINGS):
            issues.append("dangling_opening: use an 'As an...' construction")

        text = " ".join(body)
        detected = [
            word for word in cls.FORBIDDEN_BUZZWORDS
            if re.search(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE)
        ]
        if detected:
            issues.append(f"excessive_buzzwords: {', '.join(detected)}")
        sentences = [sentence.strip() for sentence in re.split(r"[.!?]+(?:\s+|$)", text) if sentence.strip()]
        if sentences:
            average_words = sum(len(sentence.split()) for sentence in sentences) / len(sentences)
            if average_words > 25:
                issues.append(f"low_readability: average sentence length {average_words:.1f} words (max 25)")

        seen: dict[tuple[str, ...], int] = {}
        for paragraph_index, paragraph in enumerate(body):
            words = [re.sub(r"[^\w'-]", "", word).casefold() for word in paragraph.split()]
            words = [word for word in words if word]
            for index in range(max(0, len(words) - ngram_size + 1)):
                ngram = tuple(words[index:index + ngram_size])
                previous = seen.get(ngram)
                if previous is not None and previous != paragraph_index:
                    issues.append(
                        "cross_paragraph_repetition: "
                        f"{' '.join(ngram)} (paragraphs {previous + 1} and {paragraph_index + 1})"
                    )
                else:
                    seen[ngram] = paragraph_index
        return CriticResult(not issues, tuple(dict.fromkeys(issues)))