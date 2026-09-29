from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import TailoredResume, validate_master_cv


def _digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evidence_fingerprints(master_cv: dict[str, Any]) -> dict[str, str]:
    cv = validate_master_cv(master_cv)
    return {
        item.source_item_id or f"section:{section_index}:item:{item_index}": _digest(
            {"title": item.title, "organization": item.organization,
             "dates": item.dates, "bullets": item.bullets}
        )
        for section_index, section in enumerate(cv.sections)
        for item_index, item in enumerate(section.items)
    }


def payload_cache_key(
    master_cv: dict[str, Any],
    jd_analysis: dict[str, Any],
    layout_budget: dict[str, Any],
    *,
    model_name: str = "",
    prompt_fingerprint: str = "",
) -> str:
    return _digest({
        "cache_version": 2,
        "cv": validate_master_cv(master_cv).model_dump(),
        "items": evidence_fingerprints(master_cv),
        "jd": jd_analysis,
        "layout": layout_budget,
        "model_name": model_name,
        "prompt_fingerprint": prompt_fingerprint,
    })


class VerifiedPayloadCache:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory).expanduser().resolve()

    def load(self, key: str) -> dict[str, Any] | None:
        path = self.directory / f"{key}.json"
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("key") != key or not data.get("verified"):
            return None
        return TailoredResume.model_validate(data["payload"]).model_dump()

    def store(self, key: str, payload: dict[str, Any]) -> None:
        validated = TailoredResume.model_validate(payload)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = self.directory / f"{key}.json"
        temporary = self.directory / f".{key}.tmp"
        temporary.write_text(json.dumps({
            "key": key, "verified": True, "payload": validated.model_dump()
        }, ensure_ascii=False), encoding="utf-8")
        temporary.replace(destination)