from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

COVER_LETTER_TARGET_MIN_WORDS = 280
COVER_LETTER_TARGET_MAX_WORDS = 340
COVER_LETTER_HARD_MIN_WORDS = 245
COVER_LETTER_HARD_MAX_WORDS = 350


@dataclass(frozen=True)
class Settings:
    api_key: str | None = None
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout_seconds: float = 90.0
    output_dir: str = "output"
    master_cv_path: str | None = None
    verified_cache_dir: str | None = None

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(encoding="utf-8-sig")
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if api_key.casefold() in {"replace_me", "your-key", "changeme"}:
            api_key = ""
        output_dir = Path(os.getenv("CAREER_SKILL_OUTPUT_DIR", "output")).expanduser().resolve()
        return cls(
            api_key=api_key or None,
            base_url=os.getenv("DEEPSEEK_BASE_URL", cls.base_url),
            model=os.getenv("DEEPSEEK_MODEL", cls.model),
            timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "90")),
            output_dir=str(output_dir),
            master_cv_path=os.getenv("CAREER_SKILL_MASTER_CV_PATH", "").strip() or None,
            verified_cache_dir=os.getenv("CAREER_SKILL_VERIFIED_CACHE_DIR", "").strip() or None,
        )
