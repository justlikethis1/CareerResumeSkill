import asyncio
import json

from career_resume_skill.server import (
    archetypes_resource,
    master_cv_resource,
    mcp,
    template_styles_resource,
    workflow_full_tailoring,
    workflow_quick_audit,
)


def test_mcp_registers_only_canonical_jd_analysis_tool() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = [tool.name for tool in tools]

    assert names.count("analyze_job_description") == 1
    assert "analyze_target_jd" not in names


def test_mcp_resources_return_safe_structured_snapshots() -> None:
    master_cv = json.loads(master_cv_resource())
    archetypes = json.loads(archetypes_resource())
    templates = json.loads(template_styles_resource())

    assert master_cv["name"] == ""
    assert master_cv["sections"] == []
    assert "ai_research" in archetypes
    assert templates["target_bullet_lines"] == 2
    assert "jakegut-resume" in templates["latex_templates"]


def test_mcp_prompts_define_full_and_audit_workflows() -> None:
    full = workflow_full_tailoring("JD text", "Example Co")
    audit = workflow_quick_audit("JD text")

    assert "analyze_job_description" in full
    assert "analyze_job_description" in audit
    assert "analyze_target_jd" not in full
    assert "analyze_target_jd" not in audit
    assert "inject_docx_in_situ" in full
    assert "must never invoke an LLM" in full
    assert "Do not rewrite bullets" in audit