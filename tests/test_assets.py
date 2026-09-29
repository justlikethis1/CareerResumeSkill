import json
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

from career_resume_skill.assets import (
    _json_file_lock,
    append_experience,
    historical_gap_reminders,
    record_application,
)
from career_resume_skill.models import MasterCV


def _record_concurrent_application(ledger: str, pdf: str, index: int) -> None:
    record_application(ledger, f"Company {index}", ["PyTorch"], pdf, 80, [])


def test_append_experience_requires_evidence_and_keeps_previous_version(tmp_path: Path) -> None:
    cv_path = tmp_path / "private_cv.json"
    cv_path.write_text(json.dumps({
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "sections": [], "skills": {},
    }), encoding="utf-8")
    previous = cv_path.read_bytes()
    with pytest.raises(ValueError, match="absent from source"):
        append_experience(cv_path, "research", "Benchmark", ["Tested Python."], ["5.2%"], [])
    assert cv_path.read_bytes() == previous

    result = append_experience(
        cv_path, "research", "Benchmark", ["Tested Python with a 5.2% gain."],
        ["5.2%"], ["Python"],
    )
    assert Path(result["previous_version_path"]).read_bytes() == previous
    cv = MasterCV.model_validate_json(cv_path.read_bytes())
    assert cv.sections[0].items[0].source_item_id == result["source_item_id"]
    with pytest.raises(ValueError, match="already exists"):
        append_experience(
            cv_path, "research", "Benchmark", ["Tested Python with a 5.2% gain."],
            ["5.2%"], ["Python"],
        )


def test_application_ledger_records_pdf_hash_without_body(tmp_path: Path) -> None:
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"private resume contents")
    ledger = tmp_path / ".career_ledger.json"
    record_application(ledger, "Example", ["Python"], pdf, 84, ["asset:123"])
    record_application(ledger, "Example", ["Python"], pdf, 84, ["asset:123"])
    entries = json.loads(ledger.read_text(encoding="utf-8"))

    assert len(entries) == 1
    assert entries[0]["pdf_sha256"] != "private resume contents"
    assert "private resume contents" not in ledger.read_text(encoding="utf-8")


@pytest.mark.parametrize("executor_type", [ThreadPoolExecutor, ProcessPoolExecutor])
def test_application_ledger_serializes_concurrent_writers(tmp_path: Path, executor_type) -> None:
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"verified pdf")
    ledger = tmp_path / ".career_ledger.json"
    with executor_type(max_workers=4) as pool:
        jobs = [
            pool.submit(_record_concurrent_application, str(ledger), str(pdf), index)
            for index in range(12)
        ]
        for job in jobs:
            job.result()
    records = json.loads(ledger.read_text(encoding="utf-8"))
    assert {entry["company"] for entry in records} == {
        f"Company {index}" for index in range(12)
    }


def test_old_lock_file_is_not_stolen_while_holder_is_active(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.json"
    with _json_file_lock(ledger):
        lock_path = tmp_path / ".ledger.json.lock"
        lock_path.touch()
        os.utime(lock_path, (0, 0))

        def try_lock() -> None:
            with _json_file_lock(ledger, timeout_seconds=0.1):
                pytest.fail("Concurrent writer stole an active lock")

        with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(
            TimeoutError, match="Timed out waiting for JSON lock"
        ):
            pool.submit(try_lock).result()


def test_ledger_reminders_remain_readable_during_parallel_writes(tmp_path: Path) -> None:
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"verified pdf")
    ledger = tmp_path / "ledger.json"
    record_application(
        ledger, "Base Company", [], pdf, 50, [],
        role_type="ai_research", missing_keywords=["PyTorch"],
    )

    def write(index: int) -> None:
        record_application(
            ledger, f"Company {index}", [], pdf, 50, [],
            role_type="ai_research", missing_keywords=["PyTorch"],
        )

    with ThreadPoolExecutor(max_workers=6) as pool:
        writes = [pool.submit(write, index) for index in range(12)]
        reads = [pool.submit(historical_gap_reminders, ledger, "ai_research") for _ in range(12)]
        for future in writes:
            future.result()
        for future in reads:
            assert future.result() == ["PyTorch"]


def test_historical_gap_reminders_are_role_scoped_and_not_taken_from_high_scores(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"verified pdf")
    ledger = tmp_path / "ledger.json"
    record_application(
        ledger, "AI Co", [], pdf, 62, [], role_type="ai_research",
        missing_keywords=["training pipelines", "PyTorch"],
    )
    record_application(
        ledger, "Other AI Co", [], pdf, 95, [], role_type="ai_research",
        missing_keywords=["ignore-high-score"],
    )
    record_application(
        ledger, "Quant Co", [], pdf, 40, [], role_type="quant_fintech",
        missing_keywords=["ignore-other-role"],
    )

    reminders = historical_gap_reminders(ledger, "ai_research")

    assert reminders == ["training pipelines", "PyTorch"]


def test_historical_gap_reminders_skip_malformed_ledger_scores(tmp_path: Path) -> None:
    ledger = tmp_path / "legacy-ledger.json"
    ledger.write_text(json.dumps([
        {"role_type": "ai_research", "ats_score": "unknown", "missing_keywords": ["bad"]},
    ]), encoding="utf-8")

    assert historical_gap_reminders(ledger, "ai_research") == []