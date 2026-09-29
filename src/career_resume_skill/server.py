from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from .application import ApplicationService
from .assets import append_experience as append_verified_experience
from .docx_engine import calculate_docx_layout_budget
from .models import validate_master_cv
from .quality import audit_docx_health as inspect_cv_health
from .quality import extract_pdf_text, lint_output_integrity

mcp = MCPServer("Career Resume Skill")
services = ApplicationService()


@mcp.tool(name="append_experience")
async def append_experience(
    section_type: str,
    title: str,
    source_bullets: list[str],
    metrics: list[str],
    tools: list[str],
) -> dict[str, Any]:
    """Append candidate-confirmed source evidence to the configured private CV with a history snapshot."""
    path = services.settings.master_cv_path
    if not path:
        raise ValueError("Configure CAREER_SKILL_MASTER_CV_PATH before appending experience")
    return await asyncio.to_thread(
        append_verified_experience, path, section_type, title, source_bullets, metrics, tools
    )


@mcp.resource(
    "cv://master_cv.json",
    name="master_cv",
    description="Candidate-controlled source-of-truth resume facts; defaults to an empty template.",
    mime_type="application/json",
)
def master_cv_resource() -> str:
    configured_path = services.settings.master_cv_path
    if configured_path:
        content = json.loads(Path(configured_path).expanduser().read_text(encoding="utf-8"))
        content = validate_master_cv(content).model_dump()
    else:
        content = {
            "name": "",
            "contact": {"email": "", "phone": "", "location": "", "linkedin": "", "github": ""},
            "profile": "",
            "sections": [],
            "skills": {},
        }
    return json.dumps(content, ensure_ascii=False, indent=2)


@mcp.resource(
    "config://archetypes.json",
    name="archetypes",
    description="Role archetypes and evidence-safe target terminology.",
    mime_type="application/json",
)
def archetypes_resource() -> str:
    return json.dumps(
        {
            "quant_fintech": ["latency", "numerical precision", "backtesting", "concurrency", "risk"],
            "systems_infra": ["throughput", "scalability", "memory and I/O bottlenecks", "caching", "deployment"],
            "ai_research": ["training dynamics", "preference alignment", "OOD robustness", "evaluation rigor"],
            "data_engineering": ["pipeline reliability", "data quality", "orchestration", "lineage", "scale"],
            "general_software": ["modular architecture", "API contracts", "integration", "delivery"],
            "policy": "Use target terms only when supported by cited candidate evidence.",
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.resource(
    "templates://styles.json",
    name="template_styles",
    description="Available LaTeX styles and original-DOCX layout policy.",
    mime_type="application/json",
)
def template_styles_resource() -> str:
    template_root = Path(__file__).resolve().parents[2] / "templates" / "latex"
    templates = sorted(path.name for path in template_root.iterdir() if path.is_dir()) if template_root.is_dir() else []
    return json.dumps(
        {
            "latex_templates": templates,
            "docx_mode": "preserve original OOXML package, run styles, tables, and media",
            "font_measurement": "Pillow font metrics with local-font fallback",
            "target_bullet_lines": 2,
            "target_line_occupancy_ratio": [0.85, 0.92],
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.prompt(name="workflow_full_tailoring", description="Evidence-bound end-to-end resume tailoring workflow.")
def workflow_full_tailoring(jd_text: str, company_name: str) -> str:
    return (
        "Read cv://master_cv.json and config://archetypes.json. Call analyze_job_description with the supplied JD, "
        "then generate_tailored_payload with the CV and analysis. If the input is an original DOCX, call "
        "import_docx_master_cv and calculate_layout_budget first, pass source_item_map and layout_budget into "
        "generate_tailored_payload, then call inject_docx_in_situ; this tool is deterministic and must "
        "never invoke an LLM. Compile and verify the PDF, and report evidence gaps and integrity findings. "
        f"Company: {company_name}. JD: {jd_text}"
    )


@mcp.prompt(name="workflow_quick_audit", description="Analyze JD fit and evidence gaps without generating documents.")
def workflow_quick_audit(jd_text: str) -> str:
    return (
        "Read cv://master_cv.json, call analyze_job_description, then compare must-haves and preferred terms with "
        "verified evidence. Return supported matches, transferable evidence, and explicit gaps only. "
        "Do not rewrite bullets or generate files. JD: " + jd_text
    )


@mcp.tool(name="calculate_layout_budget")
async def calculate_layout_budget(source_docx: str) -> dict[str, Any]:
    """Measure source DOCX paragraph widths and estimated wrapped lines using local font metrics."""
    return await asyncio.to_thread(calculate_docx_layout_budget, source_docx)


@mcp.tool(name="audit_cv_health")
async def audit_cv_health(source_docx: str) -> dict[str, Any]:
    """Inspect source DOCX text, table widths and font-based line estimates without model or PDF."""
    return await asyncio.to_thread(inspect_cv_health, source_docx)


@mcp.tool(name="generate_tailored_payload")
async def generate_tailored_payload(
    master_cv_json: dict[str, Any],
    jd_analysis: dict[str, Any],
    ctx: Context,
    source_item_map: dict[str, Any] | None = None,
    layout_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a schema-validated, evidence-bound resume payload without rendering files."""
    jd_analysis = dict(jd_analysis)
    if source_item_map is not None:
        jd_analysis["source_item_map"] = source_item_map
    if layout_budget is not None:
        jd_analysis["layout_budget"] = layout_budget
    await ctx.info("Starting tailored payload generation; candidate content is not written to protocol logs.")
    result = await services.tailor_resume_content(master_cv_json, jd_analysis)
    bullet_count = sum(
        len(item.get("bullets", []))
        for section in result.get("sections", [])
        for item in section.get("items", [])
    )
    await ctx.info(f"Tailored payload complete: {bullet_count} bullets; model={result.get('model_used')}.")
    return result


@mcp.tool(name="inject_docx_in_situ")
async def inject_docx_in_situ(
    source_docx: str,
    output_docx: str,
    paragraph_replacements: dict[str, str],
) -> dict[str, Any]:
    """Perform deterministic OOXML text injection only; no model call is made."""
    return await services.inject_docx_layout(source_docx, output_docx, paragraph_replacements)


@mcp.tool(name="compile_and_verify_pdf")
async def compile_and_verify_pdf(
    docx_path: str,
    source_evidence_text: str = "",
    bullet_texts: list[str] | None = None,
) -> dict[str, Any]:
    """Convert DOCX to PDF and report strict one-page, metric, punctuation, and glyph checks."""
    result = await services.convert_docx_to_pdf(docx_path)
    pages, text = extract_pdf_text(result["pdf_path"])
    integrity = lint_output_integrity(
        source_evidence_text,
        text,
        pages,
        expected_pages=1,
        bullet_texts=bullet_texts,
    )
    return {**result, "pages": pages, "integrity": integrity, "verified": integrity["passed"]}

@mcp.tool()
async def analyze_job_description(jd_text: str) -> dict[str, Any]:
    """Extract role archetype, must-haves, nice-to-haves, and ATS keywords from JD text or URL."""
    return await services.analyze_job_description(jd_text)


@mcp.tool()
async def tailor_resume_content(
    master_cv_json: dict[str, Any], jd_analysis: dict[str, Any]
) -> dict[str, Any]:
    """Truthfully select, reorder, and rewrite Master CV content for the analyzed JD."""
    return await services.tailor_resume_content(master_cv_json, jd_analysis)


@mcp.tool()
async def draft_cover_letter(
    tailored_cv: dict[str, Any],
    company_name: str,
    tone: str = "professional and concise",
    verified_company_context: str = "",
) -> dict[str, Any]:
    """Draft a three-paragraph evidence-bound cover letter."""
    return await services.draft_cover_letter(
        tailored_cv, company_name, tone, verified_company_context
    )


@mcp.tool()
async def inspect_docx_layout(
    source_path: str,
    resources_dir: str | None = None,
    manifest_path: str | None = None,
) -> dict[str, Any]:
    """Extract DOCX styles, paragraph IDs, table paths, layout metadata, and images."""
    return await services.inspect_docx_layout(source_path, resources_dir, manifest_path)


@mcp.tool()
async def import_docx_master_cv(source_path: str) -> dict[str, Any]:
    """Convert a real DOCX resume into a conservative Master CV plus paragraph evidence mapping."""
    return await services.import_docx_master_cv(source_path)


@mcp.tool()
async def generate_docx_application_package(
    docx_source: str,
    jd_text: str,
    output_docx: str,
    company_name: str,
    tone: str = "professional and concise",
    verified_company_context: str = "",
    resume_language: str = "en",
    application_date: str = "",
) -> dict[str, Any]:
    """Tailor a DOCX-derived Master CV and inject only existing bullet paragraphs into the original template."""
    return await services.generate_docx_application_package(
        docx_source,
        jd_text,
        output_docx,
        company_name,
        tone,
        verified_company_context,
        resume_language,
        application_date,
    )


@mcp.tool()
async def inject_docx_layout(
    source_path: str,
    output_path: str,
    replacements: dict[str, str],
    enforce_length_budget: bool = True,
) -> dict[str, Any]:
    """Replace mapped paragraph text in-place while preserving the original DOCX package."""
    return await services.inject_docx_layout(
        source_path, output_path, replacements, enforce_length_budget
    )


@mcp.tool()
async def convert_docx_to_pdf(
    docx_path: str,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Convert an injected DOCX to PDF through LibreOffice headless."""
    return await services.convert_docx_to_pdf(docx_path, output_dir)


@mcp.tool()
async def check_environment() -> dict[str, Any]:
    """Report API, dependency, compiler, and output-directory readiness without exposing secrets."""
    return services.check_environment()


@mcp.tool()
async def render_and_compile_latex(
    tex_template_name: str,
    content_json: dict[str, Any],
    page_limit: int = 1,
) -> dict[str, Any]:
    """Escape content, render a bundled LaTeX template, and compile it to PDF."""
    return await services.render_and_compile_latex(
        tex_template_name, content_json, page_limit
    )


@mcp.tool()
async def generate_application_package(
    jd_text: str,
    master_cv_json: dict[str, Any],
    company_name: str,
    tone: str = "professional and concise",
    verified_company_context: str = "",
    application_date: str = "",
    page_limit: int = 1,
    compile_documents: bool = True,
) -> dict[str, Any]:
    """Run JD analysis through resume, cover letter, and optional PDF compilation."""
    return await services.generate_application_package(
        jd_text,
        master_cv_json,
        company_name,
        tone,
        verified_company_context,
        application_date,
        page_limit,
        compile_documents,
    )


def main() -> None:
    transport = os.getenv("CAREER_SKILL_MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run(transport=transport)
    elif transport == "streamable-http":
        mcp.run(
            transport=transport,
            host=os.getenv("CAREER_SKILL_MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("CAREER_SKILL_MCP_PORT", "8000")),
        )
    else:
        raise ValueError("CAREER_SKILL_MCP_TRANSPORT must be 'stdio' or 'streamable-http'")


if __name__ == "__main__":
    main()
