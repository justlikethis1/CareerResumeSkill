import asyncio
from pathlib import Path

from career_resume_skill.analysis import analyze_job_description_local
from career_resume_skill.config import Settings
from career_resume_skill.latex import render_template
from career_resume_skill.llm import DeepSeekClient
from career_resume_skill.tailoring import draft_cover, tailor_resume


def test_fallback_pipeline_renders_both_documents(tmp_path: Path) -> None:
    master_cv = {
        "name": "Candidate",
        "contact": {"email": "candidate@example.com"},
        "profile": "Python and PyTorch engineer.",
        "sections": [
            {"type": "education", "title": "Education", "items": []},
            {"type": "projects", "title": "Projects", "items": []},
        ],
        "skills": {"Languages": ["Python"], "ML": ["PyTorch"]},
    }
    analysis = analyze_job_description_local("AI Lab research role using Python and PyTorch")
    client = DeepSeekClient(Settings(api_key=None))

    tailored = asyncio.run(tailor_resume(master_cv, analysis, client))
    cover = asyncio.run(draft_cover(tailored, "Target Company", "concise", client))
    resume_path = render_template("resume", tailored, tmp_path / "resume.tex")
    cover_payload = {
        **cover,
        "name": tailored["name"],
        "company_name": "Target Company",
        "date": "September 24, 2026",
        "contact": tailored["contact"],
    }
    cover_path = render_template("cover_letter", cover_payload, tmp_path / "cover.tex")

    assert tailored["model_used"] == "deterministic_fallback"
    assert cover["model_used"] == "deterministic_fallback"
    assert cover["evidence_ids"]
    assert resume_path.exists()
    assert cover_path.exists()
    assert "Target Company" in cover_path.read_text(encoding="utf-8")
