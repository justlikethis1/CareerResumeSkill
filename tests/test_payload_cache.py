import asyncio
import json
from pathlib import Path

from career_resume_skill.application import ApplicationService
from career_resume_skill.config import Settings
from career_resume_skill.payload_cache import (
    VerifiedPayloadCache,
    evidence_fingerprints,
    payload_cache_key,
)


def test_fingerprint_changes_for_source_evidence_and_layout() -> None:
    cv = json.loads(Path("examples/master_cv.json").read_text(encoding="utf-8"))
    initial = evidence_fingerprints(cv)
    jd = {"role_type": "ai_research", "must_haves": ["Python"]}
    layout = {"paragraphs": [{"available_width_pt": 480}]}
    key = payload_cache_key(cv, jd, layout)

    changed = json.loads(json.dumps(cv))
    changed["sections"][0]["items"][0]["bullets"][0] += " Verified detail."

    assert initial != evidence_fingerprints(changed)
    assert key != payload_cache_key(changed, jd, layout)
    assert key != payload_cache_key(cv, {**jd, "must_haves": ["PyTorch"]}, layout)
    assert key != payload_cache_key(cv, jd, {"paragraphs": [{"available_width_pt": 460}]} )
    assert key != payload_cache_key(cv, jd, layout, model_name="different-model")
    assert key != payload_cache_key(cv, jd, layout, prompt_fingerprint="new-prompt")


def test_tailoring_prompt_fingerprint_tracks_role_and_language() -> None:
    from career_resume_skill.tailoring import tailoring_prompt_fingerprint

    base = tailoring_prompt_fingerprint("ai_research", "en")

    assert base != tailoring_prompt_fingerprint("quant_fintech", "en")
    assert base != tailoring_prompt_fingerprint("ai_research", "zh_CN")


def test_cache_rejects_unverified_entry(tmp_path: Path) -> None:
    cache = VerifiedPayloadCache(tmp_path)
    key = "abc123"
    (tmp_path / f"{key}.json").write_text(
        json.dumps({"key": key, "verified": False, "payload": {}}), encoding="utf-8"
    )

    assert cache.load(key) is None


def test_verified_cache_round_trip(tmp_path: Path) -> None:
    class Offline:
        available = False
        model_name = "deterministic_fallback"

    cv = json.loads(Path("examples/master_cv.json").read_text(encoding="utf-8"))
    service = ApplicationService(Settings(output_dir=str(tmp_path)), provider=Offline())
    analysis = {"role_type": "ai_research", "must_haves": ["Python"]}
    tailored = asyncio.run(service.tailor_resume_content(cv, analysis))
    key = payload_cache_key(cv, analysis, {"paragraphs": []})
    cache = VerifiedPayloadCache(tmp_path)

    cache.store(key, tailored)

    assert cache.load(key) == tailored