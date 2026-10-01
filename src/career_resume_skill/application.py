from __future__ import annotations

import asyncio
import shutil
import tempfile
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .analysis import (
    allocate_item_bullet_budgets,
    analyze_job_description_local,
    build_evidence_index,
    build_gap_analysis,
    filter_atomic_requirements,
)
from .artifacts import create_run_directory, slug
from .assets import historical_gap_reminders, record_application
from .ats import score_ats
from .config import Settings
from .critic import CoverLetterCritic, DocxCritic, TextContentCritic
from .docx_engine import (
    calculate_docx_layout_budget,
    convert_docx_to_pdf,
    inject_docx_bullet_groups,
    inject_docx_text,
    inspect_docx,
)
from .docx_profile import import_docx_as_master_cv
from .facts import build_fact_cards
from .ingestion import resolve_jd_source
from .latex import PageLimitError, compile_latex, prune_low_priority_resume, render_template
from .llm import LLMProvider
from .models import (
    COVER_LETTER_HARD_MAX_WORDS,
    COVER_LETTER_HARD_MIN_WORDS,
    JDAnalysis,
    validate_jd_analysis,
    validate_master_cv,
)
from .payload_cache import VerifiedPayloadCache, payload_cache_key
from .quality import (
    document_quality_report,
    extract_pdf_text,
    lint_output_integrity,
    lint_payload_bullets,
)
from .refinement import refine_one_bullet
from .tailoring import draft_cover, tailor_resume, tailoring_prompt_fingerprint
from .tools import environment_report

JD_ANALYSIS_TASK = """Analyze the job description without adding outside facts. Return a JSON object with:
role_type (quant_fintech, finance_operations, systems_infra, ai_research, data_engineering, hr_recruiting,
administration, customer_service, hospitality_food_service, retail_sales, or general_software), must_haves,
nice_to_haves, ats_keywords, education, experience_years, business_domains, hard_skills, soft_skills,
core_technical_pain_points, semantic_mapping_strategy, semantic_mapping_directives, and rationale. Use arrays
except role_type, experience_years, education, and rationale. Preserve exact JD terminology where practical.

Identify the top three technical pain points. For each major candidate evidence domain visible in INPUT_JSON,
produce a semantic_mapping_directive with:
- source_domain: a stable domain label such as multimodal_post_training, multi_agent_system, time_series_forecasting,
  simulation_modeling, backend_service, or data_pipeline;
- target_lexicon: exact JD phrases that are technically equivalent and safe to use;
- engineering_angle: how the verified problem/solution should answer the hiring manager's pain point;
- expected_focus: the primary emphasis, such as convergence, evaluation, latency, throughput, reliability, or scale.

Do not authorize unverified tools or responsibilities. The directives are lexical framing instructions, not new facts."""


def _candidate_text(candidate: dict[str, Any]) -> str:
    return " ".join(fact["text"] for fact in build_fact_cards(candidate))


def _candidate_technology_source_text(candidate: dict[str, Any]) -> str:
    contact = candidate.get("contact") or {}
    contact_links = " ".join(
        str(contact.get(field, "")) for field in ("linkedin", "github") if contact.get(field)
    )
    return f"{_candidate_text(candidate)} {contact_links}".strip()


def _missing_ats_keywords(ats_report: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(
        [
            *ats_report.get("hard_requirements", {}).get("missing", []),
            *ats_report.get("preferred_keywords", {}).get("missing", []),
        ]
    ))


def _failed_content_critics(report: dict[str, Any]) -> list[str]:
    names = (
        "cover_letter_critic", "cover_letter_content_critic",
        "resume_content_critic", "docx_critic",
    )
    return [
        name for name in names
        if isinstance(report.get(name), dict) and not report[name].get("passed", False)
    ]


def _score_application_package(
    jd_analysis: dict[str, Any],
    resume: dict[str, Any],
    cover_letter: dict[str, Any],
) -> dict[str, Any]:
    resume_report = score_ats(jd_analysis, _candidate_text(resume))
    cover_text = " ".join(cover_letter.get("paragraphs", []))
    package_report = score_ats(
        jd_analysis,
        f"{_candidate_text(resume)}\n{cover_text}",
    )
    package_report["scoring_scope"] = "resume_and_cover_letter"
    package_report["resume_only"] = resume_report
    return package_report


def _source_text_for_evidence(master_cv: dict[str, Any], evidence_ids: set[str]) -> str:
    return " ".join(
        record.text
        for record in build_evidence_index(master_cv)
        if record.evidence_id in evidence_ids
    )


def _candidate_bullet_evidence(candidate: dict[str, Any]) -> tuple[set[str], list[str]]:
    evidence_ids: set[str] = set()
    bullets: list[str] = []
    for section in candidate.get("sections", []):
        for item in section.get("items", []):
            evidence_ids.update(item.get("evidence_ids", []))
            bullets.extend(item.get("bullets", []))
    return evidence_ids, bullets


def _pdf_parseability(pdf_path: str) -> dict[str, Any]:
    pages, text = extract_pdf_text(pdf_path)
    return {
        "readable_text_characters": len(text),
        "page_count": pages,
        "has_extractable_text": bool(text.strip()),
    }


def _cover_letter_metadata(
    candidate_name: str,
    company_name: str,
    date_str: str,
    contact: dict[str, Any],
    jd_analysis: dict[str, Any],
) -> dict[str, Any]:
    role_titles = {
        "ai_research": "AI Research",
        "quant_fintech": "Quantitative Finance / FinTech",
        "systems_infra": "Systems Engineering",
        "data_engineering": "Data Engineering",
        "general_software": "Software Engineering",
    }
    job_title = (
        jd_analysis.get("job_title")
        or jd_analysis.get("target_role")
        or role_titles.get(jd_analysis.get("role_type"), "Software Engineering")
    )
    try:
        parsed_date = date.fromisoformat(date_str)
        date_display = f"{parsed_date:%B} {parsed_date.day}, {parsed_date.year}"
    except ValueError:
        date_display = date_str
    return {
        "name": candidate_name,
        "company_name": company_name,
        "date": date_display,
        "recipient_title": "Hiring Committee",
        "subject_line": f"RE: Application for {job_title} - {candidate_name}",
        "contact": contact,
    }


def _closing_salutation(cover_letter: dict[str, Any]) -> str:
    return cover_letter["closing"].splitlines()[0].strip().rstrip(",")


def _write_cover_letter_text(
    cover_letter: dict[str, Any], metadata: dict[str, Any], path: Path
) -> str:
    paragraphs = cover_letter["paragraphs"]
    if len(paragraphs) != 3:
        raise ValueError("Cover letter must contain exactly three paragraphs")
    contact = metadata["contact"]
    sender_contact = " | ".join(
        value for value in (contact.get("email"), contact.get("phone"), contact.get("location"))
        if value
    )
    personal_links = " | ".join(
        f"{label}: {contact[key]}"
        for key, label in (("linkedin", "LinkedIn"), ("github", "GitHub"))
        if contact.get(key)
    )
    lines = [
        metadata["name"],
        sender_contact,
        f"Date: {metadata['date']}",
        "",
        metadata["recipient_title"],
        metadata["company_name"],
        "",
        metadata["subject_line"],
        "=" * len(metadata["subject_line"]),
        "",
        cover_letter["salutation"],
        "",
    ]
    for paragraph in paragraphs:
        lines.extend((paragraph, ""))
    lines.extend((f"{_closing_salutation(cover_letter)},", "", "", "", metadata["name"]))
    if personal_links:
        lines.extend((personal_links,))
    text = "\n".join(lines).rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path.resolve())


def _write_cover_letter_markdown(
    cover_letter: dict[str, Any],
    metadata: dict[str, Any],
    path: Path,
) -> str:
    contact = metadata["contact"]
    contact_parts = [
        value
        for value in (
            contact.get("email"),
            contact.get("phone"),
            contact.get("location"),
            contact.get("linkedin"),
            contact.get("github"),
        )
        if value
    ]
    contact_line = " | ".join(contact_parts)
    paragraphs = cover_letter["paragraphs"]
    lines = [
        f"# Cover Letter — {metadata['name']}",
        contact_line,
        f"Date: {metadata['date']}",
        "",
        metadata["recipient_title"],
        metadata["company_name"],
        "",
        f"**{metadata['subject_line']}**",
        "---",
        "",
        cover_letter["salutation"],
        "",
        paragraphs[0],
        "",
        paragraphs[1],
        "",
        paragraphs[2],
        "",
        f"{_closing_salutation(cover_letter)},",
        "",
        "",
        "",
        f"**{metadata['name']}**",
    ]
    personal_links = " | ".join(
        f"[{label}]({contact[key]})"
        for key, label in (("linkedin", "LinkedIn"), ("github", "GitHub"))
        if contact.get(key)
    )
    if personal_links:
        lines.extend((personal_links,))
    md_content = "\n".join(line for line in lines if line is not None).strip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md_content, encoding="utf-8")
    return str(path.resolve())


class ApplicationService:
    """Application use cases shared by MCP, CLI, and future HTTP adapters."""

    def __init__(self, settings: Settings | None = None, provider: LLMProvider | None = None) -> None:
        self.settings = settings or Settings.from_env()
        if provider is None:
            from .llm import DeepSeekClient

            provider = DeepSeekClient(self.settings)
        self.provider = provider

    async def analyze_job_description(
        self, jd_source: str, candidate_profile: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        resolved_text, source = await resolve_jd_source(jd_source)
        local = analyze_job_description_local(resolved_text)
        if not self.provider.available:
            return {**local, "source": source, "model_used": "deterministic_fallback"}
        enhanced_model = await self.provider.complete_json(
            JD_ANALYSIS_TASK,
            {"JD_TEXT": resolved_text, "CANDIDATE_PROFILE": candidate_profile or {}},
            JDAnalysis,
            temperature=0.1,
        )
        enhanced = enhanced_model.model_dump()
        excluded_requirements: list[str] = list(
            local.get("excluded_non_atomic_requirements", [])
        )
        for key in ("must_haves", "nice_to_haves", "ats_keywords"):
            merged = list(dict.fromkeys([*local.get(key, []), *enhanced.get(key, [])]))
            enhanced[key], excluded = filter_atomic_requirements(merged)
            excluded_requirements.extend(excluded)
        enhanced["excluded_non_atomic_requirements"] = list(dict.fromkeys(excluded_requirements))
        enhanced.setdefault("role_type", local["role_type"])
        enhanced["rule_based_role_scores"] = local["role_scores"]
        enhanced["source"] = source
        enhanced["model_used"] = self.provider.model_name
        return enhanced

    async def tailor_resume_content(
        self, master_cv_json: dict[str, Any], jd_analysis: dict[str, Any]
    ) -> dict[str, Any]:
        validated_cv = validate_master_cv(master_cv_json)
        validated_jd = validate_jd_analysis(jd_analysis).model_dump()
        item_budgets = validated_jd.get("item_bullet_budgets") or allocate_item_bullet_budgets(
            validated_cv, validated_jd
        )
        source_item_map = validated_jd.get("source_item_map", {})
        paragraph_budgets = {
            paragraph["paragraph_id"]: paragraph
            for paragraph in validated_jd.get("layout_budget", {}).get("paragraphs", [])
        }
        if source_item_map:
            for item_id, budget in item_budgets.items():
                source_item = source_item_map.get(item_id, {})
                budget["paragraph_layout"] = [
                    paragraph_budgets[paragraph_id]
                    for paragraph_id in source_item.get("bullet_paragraph_ids", [])
                    if paragraph_id in paragraph_budgets
                ]
        validated_jd["item_bullet_budgets"] = item_budgets
        validated_jd["historical_gap_reminders"] = historical_gap_reminders(
            Path(self.settings.output_dir) / ".career_ledger.json",
            validated_jd.get("role_type"),
        )
        result = await tailor_resume(
            validated_cv.model_dump(), validated_jd, self.provider
        )
        result["gap_analysis"] = build_gap_analysis(validated_cv, validated_jd)
        return result

    async def draft_cover_letter(
        self,
        tailored_cv: dict[str, Any],
        company_name: str,
        tone: str = "professional and concise",
        verified_company_context: str = "",
        jd_analysis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await draft_cover(
            tailored_cv,
            company_name,
            tone,
            self.provider,
            verified_company_context,
            jd_analysis,
        )

    async def inspect_docx_layout(
        self, source_path: str, resources_dir: str | None = None, manifest_path: str | None = None
    ) -> dict[str, Any]:
        report = await asyncio.to_thread(inspect_docx, source_path, resources_dir)
        if manifest_path:
            report.write_manifest(Path(manifest_path).expanduser().resolve())
        return report.to_dict()

    async def import_docx_master_cv(self, source_path: str) -> dict[str, Any]:
        return await asyncio.to_thread(import_docx_as_master_cv, source_path)

    async def generate_docx_application_package(
        self,
        docx_source: str,
        jd_text: str,
        output_docx: str,
        company_name: str,
        tone: str = "professional and concise",
        verified_company_context: str = "",
        resume_language: str = "en",
        application_date: str = "",
    ) -> dict[str, Any]:
        if resume_language not in {"en", "zh_CN"}:
            raise ValueError("resume_language must be 'en' or 'zh_CN'")
        if resume_language == "zh_CN" and not self.provider.available:
            raise ValueError("Chinese DOCX resume requires a configured LLM provider")
        imported = await self.import_docx_master_cv(docx_source)
        jd_analysis, layout_budget = await asyncio.gather(
            self.analyze_job_description(jd_text, imported["master_cv"]),
            asyncio.to_thread(calculate_docx_layout_budget, docx_source),
        )
        jd_analysis["resume_language"] = resume_language
        item_budgets = allocate_item_bullet_budgets(imported["master_cv"], jd_analysis)
        paragraph_budgets = {
            paragraph["paragraph_id"]: paragraph
            for paragraph in layout_budget["paragraphs"]
        }
        for item_id, budget in item_budgets.items():
            source_item = imported.get("source_item_map", {}).get(item_id, {})
            budget["paragraph_layout"] = [
                paragraph_budgets[paragraph_id]
                for paragraph_id in source_item.get("bullet_paragraph_ids", [])
                if paragraph_id in paragraph_budgets
            ]
        jd_analysis["layout_budget"] = layout_budget
        jd_analysis["item_bullet_budgets"] = item_budgets
        cache = (
            VerifiedPayloadCache(self.settings.verified_cache_dir)
            if self.settings.verified_cache_dir else None
        )
        cache_key = payload_cache_key(
            imported["master_cv"],
            jd_analysis,
            layout_budget,
            model_name=self.provider.model_name,
            prompt_fingerprint=tailoring_prompt_fingerprint(
                jd_analysis.get("role_type", "general_software"), resume_language
            ),
        )
        cached = cache.load(cache_key) if cache else None
        if cached is None:
            tailored_cv = await self.tailor_resume_content(imported["master_cv"], jd_analysis)
            refinement = await refine_one_bullet(
                tailored_cv, imported["master_cv"], imported.get("source_item_map", {}),
                layout_budget, self.provider, audit_only=True, item_budgets=item_budgets,
            )
        else:
            tailored_cv = cached
            refinement = {
                "states": ["INGESTION", "PROJECTION", "GEOMETRIC_EVALUATION"],
                "outcome": "verified_cache_hit",
            }
        evidence_ids, bullet_texts = _candidate_bullet_evidence(tailored_cv)
        preflight = lint_payload_bullets(
            _source_text_for_evidence(imported["master_cv"], evidence_ids), bullet_texts,
            language=resume_language,
        )
        if not preflight["passed"]:
            raise ValueError(f"DOCX payload failed preflight integrity checks: {preflight}")
        refinement["states"].append("DOCX_INJECTION")
        bullet_groups: dict[str, dict[str, list[str]]] = {}
        source_item_map = imported.get("source_item_map", {})
        selected_bullets: dict[str, list[str]] = {}
        for section in tailored_cv.get("sections", []):
            for item in section.get("items", []):
                selected_bullets[item["source_item_id"]] = item.get("bullets", [])
        for item_id, source in source_item_map.items():
            paragraph_ids = source.get("bullet_paragraph_ids", [])
            if paragraph_ids:
                bullet_groups[item_id] = {
                    "paragraph_ids": paragraph_ids,
                    "bullets": selected_bullets.get(item_id, []),
                }
        replacement_count = sum(len(group["bullets"]) for group in bullet_groups.values())
        output_path = Path(output_docx).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        estimated_total_lines = sum(
            int(paragraph.get("estimated_source_lines", 0))
            for paragraph in layout_budget.get("paragraphs", [])
        )
        refinement["layout_heuristic"] = {
            "estimated_total_lines": estimated_total_lines,
            "initial_compact_level": 0,
            "strategy": "conservative_ascending_fallback",
        }
        with tempfile.TemporaryDirectory(prefix="career-resume-layout-", dir=output_path.parent) as temp_dir:
            temp_root = Path(temp_dir)

            def attempt_path(level: int) -> Path:
                return output_path if level == 0 else temp_root / f"{output_path.stem}-compact-{level}.docx"

            selected_level = 0
            candidate_path = attempt_path(0)
            output = await asyncio.to_thread(
                inject_docx_bullet_groups,
                docx_source,
                candidate_path,
                bullet_groups,
                compact_level=0,
            )
            pdf = await self.convert_docx_to_pdf(str(output))
            refinement["states"].append("HEADLESS_VERIFICATION")
            pages, _ = extract_pdf_text(pdf["pdf_path"])
            for level in range(1, 3):
                if pages == 1:
                    break
                candidate_path = attempt_path(level)
                candidate = await asyncio.to_thread(
                    inject_docx_bullet_groups,
                    docx_source,
                    candidate_path,
                    bullet_groups,
                    compact_level=level,
                )
                candidate_pdf = await self.convert_docx_to_pdf(str(candidate))
                candidate_pages, _ = extract_pdf_text(candidate_pdf["pdf_path"])
                refinement.setdefault("style_attempts", []).append({
                    "level": level, "pages": candidate_pages, "accepted": candidate_pages == 1,
                })
                output, pdf, pages, selected_level = candidate, candidate_pdf, candidate_pages, level
                refinement["states"].extend(["STYLE_ADJUSTMENT", "HEADLESS_VERIFICATION"])
            if pages != 1 and selected_level == 2:
                relaxed_candidate = await asyncio.to_thread(
                    inject_docx_bullet_groups,
                    docx_source,
                    temp_root / f"{output_path.stem}-compact-2-relaxed.docx",
                    bullet_groups,
                    compact_level=2,
                    protect_headings=False,
                )
                relaxed_pdf = await self.convert_docx_to_pdf(str(relaxed_candidate))
                relaxed_pages, _ = extract_pdf_text(relaxed_pdf["pdf_path"])
                refinement.setdefault("style_attempts", []).append({
                    "level": 2,
                    "pages": relaxed_pages,
                    "accepted": relaxed_pages == 1,
                    "heading_protection_relaxed": True,
                })
                output, pdf, pages = relaxed_candidate, relaxed_pdf, relaxed_pages
                refinement["heading_protection_relaxed"] = True
            if pages != 1 and self.provider.available:
                retry = await refine_one_bullet(
                    tailored_cv, imported["master_cv"], source_item_map,
                    layout_budget, self.provider, page_overflow=True, item_budgets=item_budgets,
                )
                refinement["page_retry"] = retry
                if retry["outcome"] == "patch_accepted":
                    evidence_ids, bullet_texts = _candidate_bullet_evidence(tailored_cv)
                    preflight = lint_payload_bullets(
                        _source_text_for_evidence(imported["master_cv"], evidence_ids), bullet_texts,
                        language=resume_language,
                    )
                    if not preflight["passed"]:
                        raise ValueError(f"DOCX retry payload failed preflight: {preflight}")
                    for section in tailored_cv.get("sections", []):
                        for item in section.get("items", []):
                            group = bullet_groups.get(item.get("source_item_id"))
                            if group is not None:
                                group["bullets"] = item["bullets"]
                    output = await asyncio.to_thread(
                        inject_docx_bullet_groups,
                        docx_source,
                        temp_root / f"{output_path.stem}-retry.docx",
                        bullet_groups,
                        compact_level=selected_level,
                        protect_headings=not refinement.get("heading_protection_relaxed", False),
                    )
                    pdf = await self.convert_docx_to_pdf(str(output))
                    pages, _ = extract_pdf_text(pdf["pdf_path"])
                    refinement["states"].extend(["DOCX_INJECTION", "HEADLESS_VERIFICATION"])
            if output != output_path:
                final_pdf_path = output_path.with_suffix(".pdf")
                shutil.copy2(output, output_path)
                shutil.copy2(pdf["pdf_path"], final_pdf_path)
                pdf = {"pdf_path": str(final_pdf_path)}
                pages, _ = extract_pdf_text(pdf["pdf_path"])
            output = output_path
            refinement["applied_compact_level"] = selected_level
        cover_letter = await self.draft_cover_letter(
            tailored_cv, company_name, tone, verified_company_context, jd_analysis
        )
        letter_date = application_date or datetime.now().astimezone().date().isoformat()
        candidate_facts = build_fact_cards(tailored_cv)
        ats_report = _score_application_package(jd_analysis, tailored_cv, cover_letter)
        source_pdf_dir = Path(output_docx).expanduser().resolve().parent / "source-baseline"
        cover_metadata = _cover_letter_metadata(
            tailored_cv["name"], company_name, letter_date, tailored_cv["contact"], jd_analysis
        )
        cover_payload = {
            **cover_letter,
            **cover_metadata,
            "closing": _closing_salutation(cover_letter),
        }
        source_pdf, cover_pdf = await asyncio.gather(
            self.convert_docx_to_pdf(docx_source, str(source_pdf_dir)),
            self.render_and_compile_latex(
                "cover_letter",
                cover_payload,
                page_limit=1,
                output_dir=Path(output_docx).expanduser().resolve().parent,
            ),
        )
        quality_report = await asyncio.to_thread(
            document_quality_report,
            docx_source,
            output,
            source_pdf["pdf_path"],
            pdf["pdf_path"],
            replacement_count,
            bullet_texts,
        )
        quality_report["cover_letter_critic"] = CoverLetterCritic.audit(
            cover_letter["paragraphs"]
        ).to_dict()
        quality_report["cover_letter_content_critic"] = TextContentCritic.audit_cover(
            cover_letter["paragraphs"]
        ).to_dict()
        quality_report["rewrite_fidelity"] = tailored_cv.get("strategy", {}).get(
            "rewrite_fidelity", []
        )
        _, output_pdf_text = extract_pdf_text(pdf["pdf_path"])
        quality_report["docx_critic"] = DocxCritic.audit_text(output_pdf_text).to_dict()
        quality_report["resume_content_critic"] = TextContentCritic.audit_resume(
            bullet_texts
        ).to_dict()
        integrity_report = lint_output_integrity(
            _candidate_text(imported["master_cv"]),
            output_pdf_text,
            quality_report["pages"]["output"],
            expected_pages=1,
            bullet_texts=bullet_texts,
            source_technology_text=_candidate_technology_source_text(imported["master_cv"]),
        )
        failed_critics = _failed_content_critics(quality_report)
        delivery_verified = integrity_report["passed"] and not failed_critics
        delivery_warning = None if delivery_verified else (
            "Resume package was generated for inspection but did not pass final verification: "
            f"integrity={integrity_report['passed']}; failed_critics={failed_critics}"
        )
        cover_text_path, cover_md_path = await asyncio.gather(
            asyncio.to_thread(
                _write_cover_letter_text,
                cover_letter,
                cover_metadata,
                Path(output_docx).with_name(f"{Path(output_docx).stem}-cover-letter.txt"),
            ),
            asyncio.to_thread(
                _write_cover_letter_markdown,
                cover_letter,
                cover_metadata,
                Path(output_docx).with_name(f"{Path(output_docx).stem}-cover-letter.md"),
            ),
        )
        ledger_entry = None
        if delivery_verified:
            ledger_entry = record_application(
                Path(self.settings.output_dir) / ".career_ledger.json",
                company_name,
                jd_analysis.get("ats_keywords", []),
                pdf["pdf_path"],
                ats_report["score"],
                [item_id for item_id, budget in item_budgets.items() if budget["tier"] == "tier_1"],
                role_type=jd_analysis.get("role_type"),
                missing_keywords=_missing_ats_keywords(ats_report),
            )
        if cache and (cached is None or refinement.get("page_retry", {}).get("outcome") == "patch_accepted"):
            cache.store(cache_key, tailored_cv)
        quality_report["integrity_linter"] = integrity_report
        cover_letter_word_count = sum(
            len(paragraph.split()) for paragraph in cover_letter["paragraphs"]
        )
        whitespace_ratios = [
            page.get("estimated_bottom_whitespace_ratio")
            for page in quality_report.get("visual_layout", {}).get("pages", [])
            if page.get("estimated_bottom_whitespace_ratio") is not None
        ]
        quality_report["typography_audit"] = {
            "final_page_count": quality_report["pages"]["output"],
            "applied_compact_level": refinement.get("applied_compact_level", 0),
            "line_spacing_twips": (
                220 if refinement.get("applied_compact_level") == 2 else
                225 if refinement.get("applied_compact_level") == 1 else None
            ),
            "margins_adjusted": refinement.get("applied_compact_level") == 2,
            "heading_protection_relaxed": refinement.get("heading_protection_relaxed", False),
            "cover_letter_word_count": cover_letter_word_count,
            "cl_within_target_range": (
                COVER_LETTER_HARD_MIN_WORDS
                <= cover_letter_word_count
                <= COVER_LETTER_HARD_MAX_WORDS
            ),
            "visual_density_score": (
                round(1 - sum(whitespace_ratios) / len(whitespace_ratios), 3)
                if whitespace_ratios else None
            ),
        }
        ats_report["parseability"] = {
            "readable_text_characters": quality_report["pdf"]["output"]["characters"],
            "page_count": quality_report["pages"]["output"],
            "layout_feedback": quality_report["visual_layout"],
            "quality_diagnosis": quality_report["diagnosis"],
        }
        ats_report["integrity_linter"] = integrity_report
        ats_report["delivery_verified"] = delivery_verified
        return {
            "company_name": company_name,
            "resume_language": resume_language,
            "source_docx": imported["source_docx"],
            "output_docx": str(output),
            "output_pdf": pdf["pdf_path"],
            "cover_letter": cover_letter,
            "cover_letter_text_path": cover_text_path,
            "cover_letter_md_path": cover_md_path,
            "cover_letter_pdf": cover_pdf,
            "quality_report": quality_report,
            "verified": delivery_verified,
            "warning": delivery_warning,
            "ledger_entry": ledger_entry,
            "refinement": refinement,
            "preflight": preflight,
            "replacement_count": replacement_count,
            "item_bullet_budgets": item_budgets,
            "compacted_replacement_count": 0,
            "skipped_replacements": [],
            "layout_budget_mode": "original_template_bullets_no_length_gate",
            "jd_analysis": jd_analysis,
            "tailored_cv": tailored_cv,
            "fact_cards": candidate_facts,
            "ats_report": ats_report,
        }

    async def inject_docx_layout(
        self,
        source_path: str,
        output_path: str,
        replacements: dict[str, str],
        enforce_length_budget: bool = True,
        normalize_body_italic: bool = False,
        normalize_list_bullets: bool = False,
    ) -> dict[str, Any]:
        output = await asyncio.to_thread(
            inject_docx_text,
            source_path,
            output_path,
            replacements,
            enforce_length_budget=enforce_length_budget,
            normalize_body_italic=normalize_body_italic,
            normalize_list_bullets=normalize_list_bullets,
        )
        return {"docx_path": str(output), "replacements": len(replacements)}

    async def convert_docx_to_pdf(self, docx_path: str, output_dir: str | None = None) -> dict[str, Any]:
        pdf = await asyncio.to_thread(convert_docx_to_pdf, docx_path, output_dir)
        return {"pdf_path": str(pdf)}

    def check_environment(self) -> dict[str, Any]:
        return environment_report(self.settings)

    async def render_and_compile_latex(
        self,
        tex_template_name: str,
        content_json: dict[str, Any],
        page_limit: int = 1,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        if tex_template_name not in {"resume", "cover_letter"}:
            raise ValueError("tex_template_name must be 'resume' or 'cover_letter'")
        if page_limit < 1:
            raise ValueError("page_limit must be at least 1")
        candidate = slug(str(content_json.get("name", "Candidate")))
        company = slug(str(content_json.get("company_name", "Target_Company")))
        suffix = "Resume" if tex_template_name == "resume" else "Cover_Letter"
        target_dir = (output_dir or Path(self.settings.output_dir)).expanduser().resolve()
        tex_path = target_dir / f"{candidate}_{suffix}_{company}.tex"
        attempts: list[str] = []
        render_content = content_json
        for compact in range(3):
            render_template(tex_template_name, render_content, tex_path, compact=compact)
            try:
                result = await asyncio.to_thread(compile_latex, tex_path, page_limit)
                result["compact_level"] = compact
                result["attempts"] = attempts
                result["rendered_content"] = deepcopy(render_content)
                return result
            except PageLimitError as error:
                attempts.append(str(error))
        if tex_template_name == "resume":
            for _ in range(64):
                render_content, action = prune_low_priority_resume(render_content)
                if action is None:
                    break
                attempts.append(action)
                render_template(tex_template_name, render_content, tex_path, compact=2)
                try:
                    result = await asyncio.to_thread(compile_latex, tex_path, page_limit)
                    result["compact_level"] = 2
                    result["attempts"] = attempts
                    result["rendered_content"] = deepcopy(render_content)
                    return result
                except PageLimitError as error:
                    attempts.append(str(error))
        raise RuntimeError(
            f"Unable to satisfy {page_limit}-page budget: {'; '.join(attempts)}"
        )

    async def generate_application_package(
        self,
        jd_text: str,
        master_cv_json: dict[str, Any],
        company_name: str,
        tone: str = "professional and concise",
        verified_company_context: str = "",
        application_date: str = "",
        page_limit: int = 1,
        compile_documents: bool = True,
    ) -> dict[str, Any]:
        jd_analysis = await self.analyze_job_description(jd_text, master_cv_json)
        tailored_cv = await self.tailor_resume_content(master_cv_json, jd_analysis)
        cover_letter = await self.draft_cover_letter(
            tailored_cv, company_name, tone, verified_company_context, jd_analysis
        )
        documents: dict[str, Any] = {}
        candidate_facts = build_fact_cards(tailored_cv)
        ats_report = _score_application_package(jd_analysis, tailored_cv, cover_letter)
        delivery_verified: bool | None = None
        delivery_warning: str | None = None
        ats_report["rewrite_fidelity"] = tailored_cv.get("strategy", {}).get(
            "rewrite_fidelity", []
        )
        run_id, run_dir = create_run_directory(
            self.settings.output_dir, tailored_cv["name"], company_name
        )
        letter_date = application_date or datetime.now().astimezone().date().isoformat()
        cover_metadata = _cover_letter_metadata(
            tailored_cv["name"], company_name, letter_date, tailored_cv["contact"], jd_analysis
        )
        if compile_documents:
            resume_payload = {**tailored_cv, "company_name": company_name}
            cover_payload = {
                **cover_letter,
                **cover_metadata,
                "closing": _closing_salutation(cover_letter),
            }
            resume_document, cover_document = await asyncio.gather(
                self.render_and_compile_latex(
                    "resume", resume_payload, page_limit, output_dir=run_dir
                ),
                self.render_and_compile_latex(
                    "cover_letter", cover_payload, page_limit, output_dir=run_dir
                ),
            )
            documents["resume"] = resume_document
            documents["cover_letter"] = cover_document
            final_resume_payload = documents["resume"].pop("rendered_content", resume_payload)
            tailored_cv = {
                key: value for key, value in final_resume_payload.items()
                if key != "company_name"
            }
            candidate_facts = build_fact_cards(tailored_cv)
            ats_report = _score_application_package(jd_analysis, tailored_cv, cover_letter)
            ats_report["rewrite_fidelity"] = tailored_cv.get("strategy", {}).get(
                "rewrite_fidelity", []
            )
            ats_report["parseability"] = {
                name: _pdf_parseability(document["pdf_path"])
                for name, document in documents.items()
            }
            source_index = build_evidence_index(master_cv_json)
            resume_evidence_ids, resume_bullets = _candidate_bullet_evidence(tailored_cv)
            _, resume_text = extract_pdf_text(documents["resume"]["pdf_path"])
            resume_integrity = lint_output_integrity(
                _source_text_for_evidence(master_cv_json, resume_evidence_ids),
                resume_text,
                documents["resume"]["pages"],
                expected_pages=page_limit,
                bullet_texts=resume_bullets,
                source_technology_text=_candidate_technology_source_text(master_cv_json),
            )
            cover_evidence_ids = set(cover_letter.get("evidence_ids", []))
            cover_source_text = " ".join(
                record.text for record in source_index if record.evidence_id in cover_evidence_ids
            )
            _, cover_text = extract_pdf_text(documents["cover_letter"]["pdf_path"])
            cover_integrity = lint_output_integrity(
                cover_source_text,
                cover_text,
                documents["cover_letter"]["pages"],
                expected_pages=page_limit,
                source_technology_text=_candidate_technology_source_text(master_cv_json),
            )
            ats_report["integrity_linter"] = {
                "resume": resume_integrity,
                "cover_letter": cover_integrity,
                "passed": resume_integrity["passed"] and cover_integrity["passed"],
            }
            ats_report["cover_letter_critic"] = CoverLetterCritic.audit(
                cover_letter["paragraphs"]
            ).to_dict()
            ats_report["cover_letter_content_critic"] = TextContentCritic.audit_cover(
                cover_letter["paragraphs"]
            ).to_dict()
            ats_report["resume_content_critic"] = TextContentCritic.audit_resume(
                resume_bullets
            ).to_dict()
            failed_critics = _failed_content_critics(ats_report)
            delivery_verified = ats_report["integrity_linter"]["passed"] and not failed_critics
            if delivery_verified:
                ats_report["ledger_entry"] = record_application(
                    Path(self.settings.output_dir) / ".career_ledger.json",
                    company_name,
                    jd_analysis.get("ats_keywords", []),
                    documents["resume"]["pdf_path"],
                    ats_report["score"],
                    [item_id for item_id, budget in allocate_item_bullet_budgets(
                        master_cv_json, jd_analysis
                    ).items() if budget["tier"] == "tier_1"],
                    role_type=jd_analysis.get("role_type"),
                    missing_keywords=_missing_ats_keywords(ats_report),
                )
            else:
                delivery_warning = (
                    "Compiled application was generated for inspection but did not pass final "
                    f"verification: integrity={ats_report['integrity_linter']['passed']}; "
                    f"failed_critics={failed_critics}"
                )
                ats_report["ledger_entry"] = None
        cover_text_path, cover_md_path = await asyncio.gather(
            asyncio.to_thread(
                _write_cover_letter_text,
                cover_letter,
                cover_metadata,
                run_dir / f"{slug(tailored_cv['name'])}_Cover_Letter_{slug(company_name)}.txt",
            ),
            asyncio.to_thread(
                _write_cover_letter_markdown,
                cover_letter,
                cover_metadata,
                run_dir / f"{slug(tailored_cv['name'])}_Cover_Letter_{slug(company_name)}.md",
            ),
        )
        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "jd_analysis": jd_analysis,
            "gap_analysis": tailored_cv["gap_analysis"],
            "tailored_cv": tailored_cv,
            "cover_letter": cover_letter,
            "cover_letter_text_path": cover_text_path,
            "cover_letter_md_path": cover_md_path,
            "documents": documents,
            "compile_skipped": not compile_documents,
            "verified": delivery_verified,
            "warning": delivery_warning,
            "fact_cards": candidate_facts,
            "ats_report": ats_report,
        }

