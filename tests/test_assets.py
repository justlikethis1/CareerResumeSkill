import json
from pathlib import Path

import pytest

from career_resume_skill.assets import append_experience, record_application
from career_resume_skill.models import MasterCV


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