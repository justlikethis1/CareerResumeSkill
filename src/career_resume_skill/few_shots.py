from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .facts import extract_metrics, unsupported_technology_terms
from .models import CoverLetterDraft, GeneratedResumeItem


@lru_cache(maxsize=1)
def _exemplars() -> dict[str, Any]:
    path = Path(__file__).with_name("templates") / "few_shots.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(key in data for key in ("roles", "polish", "cover")):
        raise ValueError("Few-shot configuration must define roles, polish, and cover")
    return data


def validate_exemplars() -> None:
    data = _exemplars()
    for role, example in data["roles"].items():
        if role != example["role_type"]:
            raise ValueError(f"Mismatched few-shot role: {role}")
    for example in (*data["roles"].values(), data["polish"]):
        good = GeneratedResumeItem.model_validate(example["good_case"])
        source = example["source_bullet"]
        if good.source_item_id != example["source_item_id"]:
            raise ValueError("Few-shot source item ID mismatch")
        for bullet in good.bullets:
            if bullet.evidence_ids != [f"{good.source_item_id}:bullet:0"]:
                raise ValueError("Few-shot evidence ID mismatch")
            if not bullet.text.endswith(".") or bullet.text.endswith(".."):
                raise ValueError("Few-shot bullet must end with one period")
            if unsupported_technology_terms(source, bullet.text):
                raise ValueError("Few-shot adds unsupported technologies")
            source_metrics = extract_metrics(source)
            bullet_metrics = extract_metrics(bullet.text)
            if bullet_metrics - source_metrics:
                raise ValueError(
                    f"Few-shot adds unsupported metrics/numbers: {bullet_metrics - source_metrics}"
                )
            if any(metric not in source or metric not in bullet.text
                   for metric in example["verified_metrics"]):
                raise ValueError("Few-shot drops verified metric")
    cover = CoverLetterDraft.model_validate(
        data["cover"]["good_case"], context={"allow_abbreviated_cover": True}
    )
    if extract_metrics(data["cover"]["source_evidence"]) - extract_metrics(" ".join(cover.paragraphs)):
        raise ValueError("Cover exemplar drops verified metric")


def resume_exemplars(role_type: str) -> str:
    validate_exemplars()
    data = _exemplars()
    examples = [data["roles"].get(role_type, data["roles"]["general_software"]), data["polish"]]
    lines = [
        (
            "SYNTHETIC CALIBRATION EXAMPLES ONLY: never use example: IDs or facts as candidate "
            "evidence. GOOD is a GeneratedResumeItem DTO; output the full requested schema "
            "using only MASTER_CV evidence."
        )
    ]
    for example in examples:
        lines.extend((
            f"{example['role_type']} / {example['level']} SOURCE: {example['source_bullet']}",
            "JD PAIN: " + ", ".join(example["jd_target_pain_points"]),
        ))
        lines.extend(
            f"BAD: {bad['output']} FLAW: {bad['flaw']}" for bad in example["bad_cases"]
        )
        lines.append(
            "GOOD DTO: " + json.dumps(example["good_case"], ensure_ascii=False, separators=(",", ":"))
        )
    return "\n".join(lines)


def cover_exemplar() -> str:
    validate_exemplars()
    return (
        "SYNTHETIC COVER LETTER CALIBRATION ONLY. Do not reuse its facts, ID, "
        "or candidate name. good_case matches CoverLetterDraft shape, but its "
        "paragraphs are deliberately abbreviated; follow the task's word limits.\n"
        + json.dumps(_exemplars()["cover"], ensure_ascii=False, separators=(",", ":"))
    )