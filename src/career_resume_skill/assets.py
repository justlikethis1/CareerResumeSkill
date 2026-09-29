from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import MasterCV, ResumeItem


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _json_file_lock(path: Path, timeout_seconds: float = 15.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > timeout_seconds:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for JSON lock: {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def append_experience(
    cv_path: str | Path,
    section_type: str,
    title: str,
    source_bullets: list[str],
    metrics: list[str],
    tools: list[str],
) -> dict[str, Any]:
    path = Path(cv_path).expanduser().resolve(strict=True)
    if not source_bullets or any(not bullet.strip() for bullet in source_bullets):
        raise ValueError("At least one nonempty source bullet is required")
    evidence = " ".join(source_bullets).casefold()
    missing = [term for term in (*metrics, *tools) if not term.strip() or term.casefold() not in evidence]
    if missing:
        raise ValueError(f"Declared metrics/tools absent from source bullets: {missing}")
    with _json_file_lock(path):
        original = path.read_bytes()
        cv = MasterCV.model_validate_json(original)
        fingerprint = hashlib.sha256(json.dumps(
            [section_type, title, source_bullets], ensure_ascii=False
        ).encode("utf-8")).hexdigest()[:20]
        item_id = f"asset:{fingerprint}"
        if any(item.source_item_id == item_id for section in cv.sections for item in section.items):
            raise ValueError("Experience already exists in Master CV")
        item = ResumeItem(source_item_id=item_id, title=title, bullets=source_bullets)
        section = next((section for section in cv.sections if section.type == section_type), None)
        if section is None:
            from .models import ResumeSection

            section = ResumeSection(type=section_type, title=section_type.title(), items=[])
            cv.sections.append(section)
        section.items.append(item)
        prior_digest = hashlib.sha256(original).hexdigest()
        history = path.with_name(f"{path.name}.history") / f"{prior_digest}.json"
        if not history.exists():
            history.parent.mkdir(parents=True, exist_ok=True)
            history.write_bytes(original)
        _write_json(path, cv.model_dump())
        return {"source_item_id": item_id, "previous_version_sha256": prior_digest,
                "previous_version_path": str(history)}


def record_application(
    ledger_path: str | Path,
    company: str,
    jd_keywords: list[str],
    pdf_path: str | Path,
    ats_score: int,
    hero_item_ids: list[str],
) -> dict[str, Any]:
    pdf = Path(pdf_path).expanduser().resolve(strict=True)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    path = Path(ledger_path).expanduser().resolve()
    with _json_file_lock(path):
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(entries, list):
            raise TypeError("Application ledger must be a JSON list")
        record = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "company": company,
            "jd_keywords": list(dict.fromkeys(jd_keywords)),
            "pdf_sha256": digest,
            "ats_score": ats_score,
            "hero_item_ids": hero_item_ids,
        }
        if any(entry.get("pdf_sha256") == digest and entry.get("company") == company for entry in entries):
            return record
        entries.append(record)
        _write_json(path, entries)
        return record