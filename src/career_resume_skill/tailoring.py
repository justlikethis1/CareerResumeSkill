from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any

from .analysis import (
    allocate_item_bullet_budgets,
    build_evidence_index,
    build_gap_analysis,
    score_text_relevance,
)
from .critic.cl_critic import CoverLetterCritic
from .facts import (
    build_fact_cards,
    extract_hallucination_blacklist_terms,
    extract_metrics,
    extract_technologies,
    normalize_metric,
    normalize_technology,
    unsupported_technology_terms,
)
from .few_shots import cover_exemplar, resume_exemplars
from .llm import SYSTEM_RULES, LLMProvider
from .models import (
    COVER_LETTER_TARGET_MAX_WORDS,
    COVER_LETTER_TARGET_MIN_WORDS,
    CoverLetter,
    CoverLetterDraft,
    GeneratedTailoring,
    MasterCV,
    TailoredResume,
    validate_master_cv,
)
from .quality import _is_primary_metric, _operational_counts
from .text_utils import normalize_sentence_ending, normalize_technology_casing

TAILOR_TASK = """Generate a JD-tailored resume JSON from verified evidence.

DYNAMIC PYRAMID ALLOCATION:
- Treat ITEM_BULLET_BUDGETS as per-item maximums/targets, not a request to pad or split one result into repeats.
- Keep bullets for the same source item semantically distinct; do not restate one method, dataset, metric, or outcome
    across multiple bullets. If evidence cannot support distinct bullets at the full budget, return fewer.
- Integrate tools and JD terms into grammatical action clauses. Do not append parenthetical comma-separated skill lists,
    tags, or verbless keyword strings to a bullet/profile; improve ATS readability without keyword stuffing.
- Keep the total near 8-11 bullets only when distinct evidence supports that density.
- Do not map supervised/ preference fine-tuning or DPO into online sparse-reward RL unless the source explicitly
    documents online interaction or sparse feedback. Do not describe conventional forecasting as agent trajectories.
- For DOCX items, follow each item's paragraph_layout physical width and line estimate. Aim for two rendered
    lines at roughly 85-92% of available line width; never pad with punctuation to reach a visual target.
- Treat measured line width as a local font estimate; preserve complete words and allow a short final line rather
    than forcing orphan words or synthetic filler.
- Tier 1 hero items: 3-4 bullets covering architecture/problem, methodology/depth, and verified impact.
- TIER 1 AXIS CONTRACT: when a Tier 1 item has at least three distinct supported facts, you MUST assign its bullets
    to distinct axes rather than repeating one achievement. Use A) Problem & Formulation, the bottleneck and
    technical framing; B) Algorithm & Dynamics, the mechanism, optimization, loss, or tuning strategy; C) Quantified
    Impact, the exact verified metrics and benchmark outcome; D) Systems & Reproducibility, the evaluation loop,
    automation, deployment, or operationalization. For three bullets, select three distinct supported axes; for four,
    use four only when evidence supports them. Do not repeat A/B in D, omit unsupported axes, and never paraphrase one
    source fact into multiple sibling bullets.
- Tier 2 supporting items: 2 bullets covering technical method and verified outcome.
- Tier 3 ancillary items: 1 concise evidence-dense bullet.
- Do not force equal bullet counts across items.
- LOW-RELEVANCE EVIDENCE COMPRESSION: when an item is Tier 3 or its relevance score is zero/near zero for the
    target role, compress peripheral implementation parameters, manufacturing tolerances, and background detail.
    Retain the core method, modeling/simulation approach, and verified outcome that transfer to the target role;
    do not spend a full bullet enumerating every source parameter merely because it is available.

REWRITE INTENSITY (ITEM_BULLET_BUDGETS is authoritative for each source_item_id):
- Level 1 / polish_only: ancillary or weakly related evidence. Make grammar and verb phrasing more concise;
    retain the source sentence nearly verbatim when it is clear and fits the budget. Fix only grammar, weak verbs,
    redundant filler, or final punctuation; do not force STAR or a different action verb.
- Level 2 / strategic_re_anchoring: supporting evidence. Preserve core tools, named methods, and every metric;
    reorder clauses and shift only the framing to an evidence-supported JD context.
- Level 3 / full_lexical_projection: top-ranked hero evidence. Restructure into action-first STAR and project
    relevant JD terminology deeply while preserving the exact underlying facts. Do not return source text unchanged.
- Never increase rewrite intensity because a JD asks for an unsupported technology, metric, or responsibility.
- Forecasting/time-series work must not be described as RL trajectories or long-horizon agent learning unless the
    source explicitly documents agent tasks, policies, or interactive trajectories. DPO/SFT must not be described
    as sparse online feedback or reward learning unless the source explicitly says so.
- JD requirements describe the target role, not the candidate's history. Never reuse JD terms as evidence of prior
    experience unless the cited Master CV source explicitly supports that experience and mechanism.
- These level-specific directives override general STAR and novelty advice. If evidence is sparse, be conservative.

DOMAIN PROJECTION:
- Apply JD_ANALYSIS.semantic_mapping_directives only when the cited evidence supports the mapping.
- quant_fintech: latency, numerical precision, deterministic execution, backtesting, concurrency, and risk.
- systems_infra: throughput, scalability, memory/I/O bottlenecks, caching, and production deployment.
- ai_research: training dynamics, alignment, loss/policy stability, OOD robustness, and evaluation rigor.
- data_engineering: pipeline reliability, data quality, orchestration, lineage, and scale.
- general_software: modular architecture, API contracts, integration, delivery, and user impact.

EXACT LEXICON GROUNDING:
- When an atomic JD phrase has a directly supported equivalent in the cited evidence, use the exact JD phrase
    once in a natural action clause rather than relying only on a broad synonym.
- For example, measured sub-millisecond or sub-10ms inference may support "latency optimization"; a verified
    FastAPI/BERT inference workflow may support "reliable inference pipeline" when the sentence states the
    documented evaluation or reliability context. These phrases are framing, not permission to add new systems.
- Never copy an exact JD phrase merely to improve ATS coverage. If the evidence does not support its mechanism,
    tool, scale, or ownership, keep it in evidence_gaps and omit it from candidate claims.

CONTENT FIDELITY AND DENSITY:
- Preserve every verified model/tool, metric, benchmark, award, publication, and deployment outcome from each
    selected evidence item. Do not truncate named algorithms or numbers.
- For built-in/from-scratch layouts, target 420-480 words across resume bullets. For DOCX in-situ layouts,
    ITEM_BULLET_BUDGETS and available cloned source paragraphs are authoritative.
- Compress role-irrelevant implementation detail when space is constrained; preserve the meaning and exact values
    of retained claims, but do not enumerate every peripheral source parameter solely to fill a bullet.
- Tier 1/2 bullets should usually be 32-42 words; Tier 3 bullets should usually be 20-28 words.
- Level 3 bullets should use action-first STAR: Action Verb + Architecture/Technology + Challenge/Strategy
    + exact verified Impact. Level 2 may reorder clauses; Level 1 may keep a sound source sentence unchanged.
- Every item must use its source_item_id. Every bullet must cite evidence_ids belonging to the same source item.
- Never invent metrics, technologies, scope, ownership, or responsibilities. Skills must remain a subset of
    MASTER_CV skills. Never output bullet symbols, markdown, trailing dashes, or padding inside bullet text.
- When EXACT_SUPPORTED_JD_PHRASES is supplied, use the supported phrase in at least one relevant hero/supporting
    bullet when grammatically natural; do not replace it with a vague synonym merely to be conservative.
- HISTORICAL_GAP_REMINDERS are prior ATS misses, not evidence or requirements to claim. Reuse a reminder only when
    the current item's cited Master CV evidence directly supports it; otherwise leave it as an evidence gap.
- End every bullet with one standard period. Return only the requested schema."""

COVER_TASK = f"""Draft a high-impact professional three-paragraph cover letter targeting \
{COVER_LETTER_TARGET_MIN_WORDS}-{COVER_LETTER_TARGET_MAX_WORDS} English words.

Tone: formal, objective, and contribution-focused. Avoid generic or emotional phrases:
{', '.join(CoverLetterCritic.FORBIDDEN_BUZZWORDS)}. Prefer evidence-backed active verbs such as engineered,
optimized, benchmarked, mitigated, implemented, or quantified only when the cited work supports the verb.
Use direct sentences averaging no more than 25 words; avoid informal contractions. Do not invent prestige,
employers, academic credentials, metrics, technical methods, or company initiatives.
Numeric claims must match VERIFIED_NUMERIC_CLAIMS_BY_EVIDENCE_ID for a cited evidence ID; if no matching
source value exists, omit the number. Dates are not evidence of an exact duration: do not calculate years
of experience from employment dates or invent percentages, counts, or scale from a JD requirement.

Paragraph 1 (50-70 words): hook-first value proposition. Do not begin with "I am applying", "I am writing to
apply", or "I am interested in". If the opening uses a candidate identity as a modifier, use a grammatically
complete construction such as "As an AI systems engineer who..." rather than a dangling "An AI systems engineer,
I...". In the first sentence, identify the target role and the candidate's verified technical/functional identity;
in the second sentence, surface one strongest directly relevant result as a compact value signal. Do not preview
the technical story that belongs in Paragraph 2. Keep any application-intent boilerplate to at most one short
sentence. State academic status only when verified.

Paragraph 2 (140-175 words; accepted 115-195): one cohesive deep-dive story using the two strongest evidence-backed experiences.
Explain a distinct technical bottleneck, method, evidence-supported trade-off, and verified outcome. Do not repeat
the headline claim, metric, or a distinctive phrase used in Paragraph 1; use a separate supported result or explain
the method/evaluation without restating that outcome. Weave in JD terminology via semantic_mapping_directives without
claiming unverified work. Do not produce a skill list or
relabel DPO as sparse-reward learning, or time-series forecasting as long-horizon agent trajectory modeling.
Trade-off reasoning must be grounded in the cited evidence; never invent a loss, reward, entropy objective,
constraint, or design decision. If the evidence only supports an action and outcome, describe that relationship
plainly rather than adding first-principles jargon.
When two evidence domains are used, bridge them through a shared evidence-supported method or evaluation principle;
do not join them with a bare chronological transition such as "Earlier, at...". Paragraph 3 must synthesize rather
than repeat Paragraph 2's long phrases, tools, datasets, or metrics verbatim.

Paragraph 3 (60-80 words; accepted 50-90): team alignment and active technical call to action. Use verified_company_context for any specific
company claim; otherwise discuss only the verified JD domain. Emphasize converting complex algorithms into
stable, reproducible engineering workflows, invite a technical discussion, and thank the reader briefly.

ANTI-REPETITION:
- Make Paragraph 3 synthesize the candidate's value with fresh wording. Avoid repeating distinctive 6+ word phrases,
  technical constructs, or metrics already used in Paragraphs 1 and 2; maintain conceptual continuity without
  reusing the same sentence frame.
- Across all paragraphs, do not reuse a distinctive 6+ word sequence or repeat the same metric/result claim.
    Assign each paragraph a separate job: headline value, technical method, then role/team alignment.

EXACT LEXICON GROUNDING:
- Prefer one or two exact JD phrases when the cited evidence directly supports their underlying method and result.
    For instance, measured sub-10ms inference can be described as "latency optimization", and a documented
    FastAPI/BERT evaluation workflow can be described as a "reliable inference pipeline" when the surrounding
    sentence stays factual. Use the phrase naturally in context, never as a keyword list.
- Do not use an exact JD phrase if it would imply unsupported scale, deployment, ownership, or mechanism; truthfulness
    and cited evidence override ATS coverage.

COMPANY CLAIM SANDBOX:
- If COMPANY_CLAIM_POLICY is jd_only, do not infer or praise this company's projects, recent releases,
    geographic expansion, clients, market leadership, funding, or research achievements. Discuss only the
    supplied role's requirements and the candidate's verified contributions. Naming the company is allowed.
- If COMPANY_CLAIM_POLICY is verified_context_only, specific company claims must be supported by the
    exact verified_company_context; do not add surrounding unverified history or plans.

Hard constraints: exactly three cohesive prose paragraphs; no bullet points; closing must contain only a formal
salutation such as "Sincerely" (the typed candidate name is added by the document renderer); no generic boilerplate such as
"I am writing to apply", "My background includes", or "Relevant evidence includes". Cite all candidate claims
through EVIDENCE_INDEX. Do not transfer JD mechanisms (including long-horizon RL or sparse feedback) to candidate
Do not transfer JD mechanisms (including long-horizon RL or sparse feedback) to candidate
work unless the cited evidence documents them. If EXACT_SUPPORTED_JD_PHRASES is non-empty, use each listed phrase
once where it fits naturally; the backend has already checked that the cited evidence supports its underlying claim.
Avoid repeating distinctive multi-word phrases across paragraphs; synthesize the final paragraph with fresh wording
instead of restating the opening's "complex algorithms" or "stable workflows" construction.
Return only the requested schema."""

CHINESE_RESUME_TASK = """Write resume bullets in natural Simplified Chinese for a mainland technical recruiter.
Every generated bullet must contain Chinese narrative text even when the source bullet is entirely English.
Keep English only for verified proper names, tools, acronyms and measurements (for example Python or DPO);
never copy a whole English source sentence into an output bullet. Preserve the original Master CV skills
without translating, expanding, or reclassifying them; the renderer uses the verified source skill list.
Use concise action/problem/method/verified-result phrasing, not literal English translation. Preserve each
source item's evidence IDs, named tools and original numeric metrics exactly. Do not promote involvement to
leadership (e.g. 主导) unless the source explicitly proves ownership. End bullets with 。; keep section titles,
employer names and dates from the source. Do not invent latency, scale, deployment or model capabilities."""


def _tailoring_task(role_type: str, resume_language: str) -> str:
    return TAILOR_TASK + (
        "\n\n" + CHINESE_RESUME_TASK
        if resume_language == "zh_CN"
        else "\n\n" + resume_exemplars(role_type)
    )


def _supported_exact_jd_phrases(
    jd_analysis: dict[str, Any] | None, candidate_text: str
) -> list[str]:
    if not jd_analysis:
        return []
    normalized_candidate = candidate_text.casefold()
    supported_aliases = {
        "latency optimization": ("latency", "inference"),
        "reliable inference pipeline": ("inference", "pipeline"),
        "reliable inference pipelines": ("inference", "pipeline"),
        "reproducible training workflow": ("training", "workflow"),
        "reproducible training workflows": ("training", "workflow"),
        "model evaluation": ("model", "evaluation"),
    }
    terms: list[str] = []
    for value in jd_analysis.values():
        values = value if isinstance(value, list) else [value]
        for raw_term in values:
            term = str(raw_term).strip()
            key = re.sub(r"\s+", " ", term.casefold())
            aliases = supported_aliases.get(key)
            if (
                aliases and all(alias in normalized_candidate for alias in aliases)
            ) or (term and key in normalized_candidate):
                terms.append(term)
    return list(dict.fromkeys(terms))[:8]


def tailoring_prompt_fingerprint(role_type: str, resume_language: str) -> str:
    fingerprint_data = {
        "system_rules": SYSTEM_RULES,
        "task": _tailoring_task(role_type, resume_language),
        "schema": GeneratedTailoring.model_json_schema(),
        "temperature": 0.45,
    }
    canonical = json.dumps(
        fingerprint_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_bullet_punctuation(candidate: dict[str, Any]) -> None:
    for section in candidate.get("sections", []):
        for item in section.get("items", []):
            item["bullets"] = [
                normalize_sentence_ending(
                    bullet,
                    "zh_CN" if re.search(r"[\u4e00-\u9fff]", bullet) else "en",
                )
                for bullet in item.get("bullets", [])
            ]


def _remove_near_duplicate_bullets(candidate: dict[str, Any]) -> None:
    for section in candidate.get("sections", []):
        for item in section.get("items", []):
            retained: list[str] = []
            retained_tokens: list[set[str]] = []
            for bullet in item.get("bullets", []):
                tokens = set(re.findall(r"\w+", bullet.casefold()))
                duplicate = any(
                    (
                        tokens
                        and existing_tokens
                        and len(tokens & existing_tokens) / len(tokens | existing_tokens) >= 0.82
                    )
                    or SequenceMatcher(None, bullet.casefold(), existing.casefold()).ratio() >= 0.92
                    for existing, existing_tokens in zip(retained, retained_tokens)
                )
                if not duplicate:
                    retained.append(bullet)
                    retained_tokens.append(tokens)
            item["bullets"] = retained


def _flatten(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [str(value)]
    if isinstance(value, dict):
        return [
            text for key, child in value.items()
            if key != "id" and not key.endswith(("_id", "_ids"))
            for text in _flatten(child)
        ]
    if isinstance(value, list):
        return [text for child in value for text in _flatten(child)]
    return []


def validate_truthfulness(source: dict[str, Any], generated: dict[str, Any]) -> None:
    source_text = " ".join(_flatten(source))
    generated_text = " ".join(_flatten(generated))
    unsupported_metrics = _unsupported_numeric_claims(source_text, generated_text)
    if unsupported_metrics:
        raise ValueError(
            f"Generated content contains unsupported metrics: {sorted(unsupported_metrics)}"
        )
    semantic_projection_patterns = {
        "sparse-feedback RL": re.compile(
            r"\bsparse(?:\s*,\s*long[- ]chain)?\s+(?:reward|feedback)(?:[- ]signal)?\b",
            re.IGNORECASE,
        ),
        "long-horizon agent trajectories": re.compile(
            r"\blong[- ]horizon(?:\s+(?:agent|trajectory|trajectories|modeling|learning|training)){1,4}\b",
            re.IGNORECASE,
        ),
    }
    unsupported_projections = [
        label for label, pattern in semantic_projection_patterns.items()
        if pattern.search(generated_text) and not pattern.search(source_text)
    ]
    if unsupported_projections:
        raise ValueError(
            "Generated content contains unsupported domain projections: "
            f"{unsupported_projections}"
        )


def _unsupported_numeric_claims(source_text: str, generated_text: str) -> set[str]:
    source_years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", source_text))
    source_metrics = {normalize_metric(metric) for metric in extract_metrics(source_text)}
    generated_metrics = extract_metrics(generated_text)
    unsupported_metrics: set[str] = set()
    for metric in generated_metrics:
        if normalize_metric(metric) in source_metrics:
            continue
        if metric in {"0", "1"}:
            continue
        normalized = metric.lstrip("-")
        is_date = bool(
            re.fullmatch(r"\d{1,2}[./-](?:19|20)\d{2}", normalized)
            or re.fullmatch(r"(?:19|20)\d{2}", normalized)
        )
        if is_date and normalized[-4:] in source_years:
            continue
        unsupported_metrics.add(metric)
    return unsupported_metrics


def _unsupported_technology_claims(source_text: str, generated_text: str) -> set[str]:
    unsupported = unsupported_technology_terms(source_text, generated_text)
    unsupported |= (
        extract_hallucination_blacklist_terms(generated_text)
        - extract_hallucination_blacklist_terms(source_text)
    )
    return unsupported


def _reject_unverified_company_claims(paragraphs: list[str]) -> None:
    text = " ".join(paragraphs)
    unsupported_claims = re.compile(
        r"\b(?:your (?:company|lab|organization) (?:recently|has (?:launched|expanded|released)|"
        r"is (?:leading|pioneering|expanding))|your recent (?:launch|release|expansion)|"
        r"you (?:recently|have (?:launched|expanded|released)))\b|贵(?:司|实验室)近期",
        re.IGNORECASE,
    )
    if unsupported_claims.search(text):
        raise ValueError("Cover letter contains an unverified company-specific claim")


def verify_rewrite_fidelity(
    master_cv: MasterCV, candidate: dict[str, Any], budgets: dict[str, Any]
) -> list[dict[str, Any]]:
    source_items = {
        item.source_item_id or f"section:{section_index}:item:{item_index}": item
        for section_index, section in enumerate(master_cv.sections)
        for item_index, item in enumerate(section.items)
    }
    findings: list[dict[str, Any]] = []
    for section in candidate.get("sections", []):
        for item in section.get("items", []):
            item_id = item.get("source_item_id", "")
            source = source_items.get(item_id)
            level = budgets.get(item_id, {}).get("rewrite_intensity", "polish_only")
            if source is None or not source.bullets:
                continue
            source_tokens = [set(re.findall(r"\b\w+\b", bullet.casefold())) for bullet in source.bullets]
            source_text = " ".join(source.bullets)
            source_metrics = {normalize_metric(metric) for metric in extract_metrics(source_text)}
            for index, bullet in enumerate(item.get("bullets", [])):
                tokens = set(re.findall(r"\b\w+\b", bullet.casefold()))
                similarities = [
                    len(tokens & original) / len(tokens | original) if tokens | original else 1.0
                    for original in source_tokens
                ]
                closest_index = max(range(len(similarities)), key=similarities.__getitem__)
                similarity = similarities[closest_index]
                generated_metrics = {
                    normalize_metric(metric) for metric in extract_metrics(bullet)
                }
                unsupported_metrics = generated_metrics - source_metrics
                restored = level == "polish_only" and bool(
                    _unsupported_technology_claims(source_text, bullet) or unsupported_metrics
                )
                if restored:
                    item["bullets"][index] = source.bullets[closest_index]
                findings.append(
                    {
                        "source_item_id": item_id,
                        "bullet_index": index,
                        "level": level,
                        "word_overlap": round(similarity, 3),
                        "restored_source_bullet": restored,
                        "near_copy_warning": level == "full_lexical_projection" and similarity > 0.85,
                    }
                )
    return findings


def _restore_unsupported_numeric_claims(cv: MasterCV, result: dict[str, Any]) -> list[str]:
    restored: list[str] = []
    source_text = " ".join(_flatten(cv.model_dump()))
    if _unsupported_numeric_claims(source_text, result["profile"]):
        result["profile"] = cv.profile
        restored.append("Restored source profile after unsupported numeric claim")
    source_items = {
        item.source_item_id or f"section:{section_index}:item:{item_index}": item
        for section_index, section in enumerate(cv.sections)
        for item_index, item in enumerate(section.items)
    }
    for section in result["sections"]:
        for item in section["items"]:
            source_item = source_items[item["source_item_id"]]
            item_source = " ".join(_flatten(source_item.model_dump()))
            for index, bullet in enumerate(item["bullets"]):
                if not _unsupported_numeric_claims(item_source, bullet):
                    continue
                if not source_item.bullets:
                    continue
                bullet_tokens = set(re.findall(r"\b\w+\b", bullet.casefold()))
                closest = max(
                    source_item.bullets,
                    key=lambda original: len(bullet_tokens & set(
                        re.findall(r"\b\w+\b", original.casefold())
                    )),
                )
                item["bullets"][index] = closest
                restored.append(
                    f"Restored source bullet after unsupported numeric claim: "
                    f"{item['source_item_id']}:{index}"
                )
    return restored


async def tailor_resume(
    master_cv: dict[str, Any],
    jd_analysis: dict[str, Any],
    client: LLMProvider,
) -> dict[str, Any]:
    validated_cv = validate_master_cv(master_cv)
    master_data = validated_cv.model_dump()
    jd_analysis = dict(jd_analysis)
    item_budgets = jd_analysis.get("item_bullet_budgets") or allocate_item_bullet_budgets(
        validated_cv, jd_analysis
    )
    jd_analysis["item_bullet_budgets"] = item_budgets
    local_item_scores = {
        item_id: budget["relevance_score"]
        for item_id, budget in item_budgets.items()
    }
    gap_analysis = build_gap_analysis(validated_cv, jd_analysis)
    if not client.available:
        if jd_analysis.get("resume_language") == "zh_CN":
            raise ValueError("Chinese resume generation requires a configured LLM provider")
        result = _deterministic_tailor(master_data, jd_analysis)
        _normalize_bullet_punctuation(result)
        result.setdefault("strategy", {})["item_scores"] = local_item_scores
        result["gap_analysis"] = gap_analysis
        result["model_used"] = "deterministic_fallback"
        return TailoredResume.model_validate(result).model_dump()
    evidence_index = build_evidence_index(validated_cv)
    required_metrics_by_item = {
        record.evidence_id: sorted(extract_metrics(record.text), key=str.casefold)
        for record in evidence_index
        if extract_metrics(record.text)
    }
    task = _tailoring_task(
        jd_analysis.get("role_type", ""),
        jd_analysis.get("resume_language", "en"),
    )
    payload = {
            "MASTER_CV": master_data,
            "EVIDENCE_INDEX": [record.model_dump() for record in evidence_index],
            "FACT_CARDS": build_fact_cards(validated_cv),
            "JD_ANALYSIS": jd_analysis,
            "GAP_ANALYSIS": gap_analysis,
            "SOURCE_BULLET_BUDGETS": jd_analysis.get("source_bullet_budgets", {}),
            "ITEM_BULLET_BUDGETS": jd_analysis.get("item_bullet_budgets", {}),
            "REQUIRED_METRICS_BY_SOURCE_ITEM": required_metrics_by_item,
            "HISTORICAL_GAP_REMINDERS": jd_analysis.get("historical_gap_reminders", []),
            "EXACT_SUPPORTED_JD_PHRASES": _supported_exact_jd_phrases(
                jd_analysis,
                " ".join(record.text for record in evidence_index),
            ),
    }
    for attempt in range(2):
        generated = await client.complete_json(
            task, payload, GeneratedTailoring, temperature=0.45 if attempt == 0 else 0.25
        )
        if jd_analysis.get("resume_language") == "zh_CN":
            generated = generated.model_copy(update={"skills": validated_cv.skills})
        result = _hydrate_generated_resume(
            validated_cv, generated, jd_analysis.get("item_bullet_budgets", {})
        )
        result.setdefault("strategy", {})["item_scores"] = local_item_scores
        _remove_near_duplicate_bullets(result)
        _normalize_bullet_punctuation(result)
        unsupported_by_item: dict[str, list[str]] = {}
        untranslated_items: list[str] = []
        for section in result["sections"]:
            for item in section["items"]:
                item_id = item["source_item_id"]
                if jd_analysis.get("resume_language") == "zh_CN" and any(
                    not re.search(r"[\u4e00-\u9fff]", bullet) for bullet in item["bullets"]
                ):
                    untranslated_items.append(item_id)
                source_text = " ".join(
                    record.text for record in evidence_index
                    if record.evidence_id == item_id
                    or record.evidence_id.startswith(f"{item_id}:bullet:")
                )
                item["bullets"] = [
                    normalize_technology_casing(bullet, source_text) for bullet in item["bullets"]
                ]
                unsupported = _unsupported_technology_claims(
                    source_text, " ".join(item["bullets"])
                )
                if unsupported:
                    unsupported_by_item[item_id] = sorted(unsupported)
        result["profile"] = normalize_technology_casing(
            result["profile"], " ".join(record.text for record in evidence_index)
        )
        candidate_claims = {
            key: result.get(key)
            for key in ("profile", "sections", "skills")
            if key in result
        }
        unsupported_metrics_error = None
        try:
            validate_truthfulness(master_data, candidate_claims)
        except ValueError as error:
            if not str(error).startswith("Generated content contains unsupported metrics:"):
                raise
            unsupported_metrics_error = error
        if not unsupported_by_item and not untranslated_items and unsupported_metrics_error is None:
            break
        if attempt == 1:
            if unsupported_by_item:
                raise ValueError(
                    f"Generated content contains unverified tools/technologies: {unsupported_by_item}"
                )
            if untranslated_items:
                raise ValueError(
                    f"Chinese resume requires Chinese text in every generated bullet: {untranslated_items}"
                )
            if unsupported_metrics_error is not None:
                restored = _restore_unsupported_numeric_claims(validated_cv, result)
                if not restored:
                    raise unsupported_metrics_error
                candidate_claims = {
                    key: result.get(key) for key in ("profile", "sections", "skills")
                    if key in result
                }
                validate_truthfulness(master_data, candidate_claims)
                result["evidence_gaps"].extend(restored)
                break
        task += (
            "\n\nRewrite only claims supported by each source item's own evidence. "
            "Do not transfer a skill from the global skills list to an item without item-level proof. "
            f"Unsupported terms by source_item_id: {unsupported_by_item}. "
            f"Items with non-Chinese bullets to rewrite in Simplified Chinese: {untranslated_items}. "
            f"Unsupported numeric claims: {unsupported_metrics_error}. "
            "Remove unsupported counts and derived years of experience; retain every original verified metric."
        )
    if jd_analysis.get("resume_language") != "zh_CN":
        result["strategy"]["rewrite_fidelity"] = verify_rewrite_fidelity(
            validated_cv, result, jd_analysis.get("item_bullet_budgets", {})
        )
    result["gap_analysis"] = gap_analysis
    result["model_used"] = client.model_name
    return TailoredResume.model_validate(result).model_dump()


def _remove_unsupported_metric_sentences(
    paragraphs: list[str], source: dict[str, Any]
) -> tuple[list[str], list[str]] | None:
    source_text = " ".join(_flatten(source))
    source_metrics = {normalize_metric(metric) for metric in extract_metrics(source_text)}
    revised: list[str] = []
    gaps: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        kept: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph.strip()):
            if not _unsupported_numeric_claims(source_text, sentence):
                kept.append(sentence)
                continue
            if any(normalize_metric(metric) in source_metrics for metric in extract_metrics(sentence)):
                return None
            gaps.append(f"Removed unsupported numeric sentence from paragraph {index + 1}")
        revised.append(" ".join(kept))
    return (revised, gaps) if gaps else None


async def draft_cover(
    tailored_cv: dict[str, Any],
    company_name: str,
    tone: str,
    client: LLMProvider,
    verified_company_context: str = "",
    jd_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validated_cv = TailoredResume.model_validate(tailored_cv)
    evidence_index = build_evidence_index(validated_cv)
    source = {
        "tailored_cv": validated_cv.model_dump(),
        "company_name": company_name,
        "verified_company_context": verified_company_context,
    }
    if not client.available:
        return CoverLetter.model_validate(
            _deterministic_cover(validated_cv, company_name)
        ).model_dump()
    task = COVER_TASK + ("\n\n" + cover_exemplar() if not verified_company_context.strip() else "")
    payload = {
            **source,
            "tone": tone,
            "COMPANY_CLAIM_POLICY": (
                "verified_context_only" if verified_company_context.strip() else "jd_only"
            ),
            "EVIDENCE_INDEX": [record.model_dump() for record in evidence_index],
            "FACT_CARDS": build_fact_cards(validated_cv),
            "VERIFIED_NUMERIC_CLAIMS_BY_EVIDENCE_ID": {
                record.evidence_id: sorted({
                    normalize_metric(metric) for metric in extract_metrics(record.text)
                }, key=str.casefold)
                for record in evidence_index if extract_metrics(record.text)
            },
            "EXACT_SUPPORTED_JD_PHRASES": _supported_exact_jd_phrases(
                jd_analysis, " ".join(fact["text"] for fact in build_fact_cards(validated_cv))
            ),
    }
    all_evidence_text = " ".join(record.text for record in evidence_index)
    for attempt in range(2):
        generated = await client.complete_json(
            task, payload, CoverLetterDraft, temperature=0.45 if attempt == 0 else 0.25
        )
        critic_issues = CoverLetterCritic.audit(generated.paragraphs).issues
        unsupported_technologies = _unsupported_technology_claims(
            all_evidence_text, " ".join(generated.paragraphs)
        )
        unsupported_metrics_error = None
        try:
            validate_truthfulness(source, {
                "salutation": generated.salutation,
                "paragraphs": generated.paragraphs,
                "closing": generated.closing,
            })
        except ValueError as error:
            if not str(error).startswith("Generated content contains unsupported metrics:"):
                raise
            unsupported_metrics_error = error
        if not critic_issues and unsupported_metrics_error is None and not unsupported_technologies:
            break
        if attempt == 1:
            if critic_issues:
                raise ValueError("Cover letter critic failed: " + "; ".join(critic_issues))
            if unsupported_metrics_error is not None:
                if unsupported_technologies:
                    raise unsupported_metrics_error
                removal = _remove_unsupported_metric_sentences(generated.paragraphs, source)
                if removal is None:
                    raise unsupported_metrics_error
                revised_paragraphs, gaps = removal
                try:
                    generated = CoverLetterDraft.model_validate({
                        **generated.model_dump(), "paragraphs": revised_paragraphs,
                        "evidence_gaps": [*generated.evidence_gaps, *gaps],
                    })
                except ValueError:
                    raise unsupported_metrics_error from None
                if CoverLetterCritic.audit(generated.paragraphs).issues:
                    raise unsupported_metrics_error
                validate_truthfulness(source, {
                    "salutation": generated.salutation,
                    "paragraphs": generated.paragraphs,
                    "closing": generated.closing,
                })
                break
            raise ValueError(
                "Cover letter contains technologies absent from cited evidence: "
                f"{sorted(unsupported_technologies)}"
            )
        if critic_issues:
            task += (
                "\n\nRewrite the entire cover letter while preserving cited facts and word budgets. Fix: "
                + "; ".join(critic_issues)
            )
        if unsupported_metrics_error is not None:
            task += (
                "\n\nRemove unsupported numeric claims and derived durations. "
                "Keep every original verified metric and cited fact. "
                f"Problem: {unsupported_metrics_error}."
            )
        if unsupported_technologies:
            task += (
                "\n\nRemove technologies not found in the candidate's source evidence: "
                f"{sorted(unsupported_technologies)}. Do not claim tools merely because the JD requests them."
            )
        if any(issue.startswith("cross_paragraph_repetition:") for issue in critic_issues):
            task += (
                " Rewrite the later paragraph named by each repetition issue around a different "
                "evidence-backed result or technical method. Do not just synonym-swap the repeated phrase, "
                "and do not repeat the same metric or central claim across paragraphs."
            )
    result = generated.model_dump()
    result["paragraphs"] = [
        re.sub(
            r"\bthe AI chip and system research center\b",
            "the AI Chip and System Research Center",
            paragraph,
            flags=re.IGNORECASE,
        )
        for paragraph in result["paragraphs"]
    ]
    _validate_evidence_ids(result["evidence_ids"], evidence_index)
    cited_ids = set(result["evidence_ids"])
    cited_source = " ".join(
        record.text for record in evidence_index if record.evidence_id in cited_ids
    )
    result["paragraphs"] = [
        normalize_technology_casing(paragraph, cited_source) for paragraph in result["paragraphs"]
    ]
    unsupported_technologies = _unsupported_technology_claims(
        cited_source, " ".join(result["paragraphs"])
    )
    if unsupported_technologies:
        for technology in unsupported_technologies:
            normalized = normalize_technology(technology)
            supporting_ids = [
                record.evidence_id
                for record in evidence_index
                if normalized in {
                    normalize_technology(candidate)
                    for candidate in extract_technologies(record.text)
                }
            ]
            cited_ids.update(supporting_ids[:2])
        result["evidence_ids"] = list(dict.fromkeys(cited_ids))
        cited_source = " ".join(
            record.text for record in evidence_index if record.evidence_id in cited_ids
        )
        unsupported_technologies = _unsupported_technology_claims(
            cited_source, " ".join(result["paragraphs"])
        )
    if unsupported_technologies:
        raise ValueError(
            "Cover letter contains technologies absent from cited evidence: "
            f"{sorted(unsupported_technologies)}"
        )
    if not verified_company_context.strip():
        _reject_unverified_company_claims(result["paragraphs"])
    letter_claims = {
        key: result.get(key)
        for key in ("salutation", "paragraphs", "closing")
        if key in result
    }
    validate_truthfulness(source, letter_claims)
    result["model_used"] = client.model_name
    return CoverLetter.model_validate(result).model_dump()


def _validate_evidence_ids(evidence_ids: list[str], evidence_index: list[Any]) -> None:
    known_ids = {record.evidence_id for record in evidence_index}
    unknown_ids = set(evidence_ids) - known_ids
    if unknown_ids:
        raise ValueError(f"Unknown evidence IDs: {sorted(unknown_ids)}")


def _hydrate_generated_resume(
    cv: MasterCV,
    generated: GeneratedTailoring,
    item_budgets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_index = build_evidence_index(cv)
    _validate_evidence_ids(generated.profile_evidence_ids, evidence_index)
    item_records = {
        record.evidence_id: record for record in evidence_index if record.kind == "item"
    }
    hydrated_by_source_type: dict[str, list[dict[str, Any]]] = {}
    used_item_ids: set[str] = set()
    budgets = item_budgets or {}
    for generated_section in generated.sections:
        for generated_item in generated_section.items:
            if generated_item.source_item_id in used_item_ids:
                raise ValueError(f"Duplicate source item: {generated_item.source_item_id}")
            record = item_records.get(generated_item.source_item_id)
            if record is None or record.section_index is None or record.item_index is None:
                raise ValueError(f"Unknown source item: {generated_item.source_item_id}")
            source_section = cv.sections[record.section_index]
            hydrated_bullets: list[str] = []
            item_evidence_ids: list[str] = []
            evidence_prefix = f"{generated_item.source_item_id}:bullet:"
            maximum_bullets = budgets.get(generated_item.source_item_id, {}).get("bullets")
            bullets = generated_item.bullets[:int(maximum_bullets)] if maximum_bullets else generated_item.bullets
            for generated_bullet in bullets:
                _validate_evidence_ids(generated_bullet.evidence_ids, evidence_index)
                if not any(
                    evidence_id == generated_item.source_item_id
                    or evidence_id.startswith(evidence_prefix)
                    for evidence_id in generated_bullet.evidence_ids
                ):
                    raise ValueError(
                        f"Bullet for {generated_item.source_item_id} must cite its own source bullet"
                    )
                hydrated_bullets.append(generated_bullet.text)
                item_evidence_ids.extend(generated_bullet.evidence_ids)
            source_item = source_section.items[record.item_index]
            hydrated_bullets, item_evidence_ids = _restore_required_metrics(
                source_item.bullets,
                generated_item.source_item_id,
                hydrated_bullets,
                item_evidence_ids,
                maximum_bullets=int(maximum_bullets) if maximum_bullets else None,
            )
            hydrated_by_source_type.setdefault(source_section.type, []).append(
                {
                    **source_item.model_dump(),
                    "source_item_id": generated_item.source_item_id,
                    "bullets": hydrated_bullets,
                    "evidence_ids": list(dict.fromkeys(item_evidence_ids)),
                }
            )
            used_item_ids.add(generated_item.source_item_id)
    hydrated_sections = [
        {
            "type": section.type,
            "title": section.title,
            "items": hydrated_by_source_type[section.type],
        }
        for section_index, section in enumerate(cv.sections)
        if section.type in hydrated_by_source_type
        and not any(previous.type == section.type for previous in cv.sections[:section_index])
    ]
    supported_skills, unsupported_skills = _filter_skill_subset(cv, generated.skills)
    evidence_gaps = list(generated.evidence_gaps)
    evidence_gaps.extend(
        f"Removed unsupported skill label: {skill}" for skill in unsupported_skills
    )
    return {
        "name": cv.name,
        "contact": cv.contact.model_dump(),
        "profile": generated.profile,
        "sections": hydrated_sections,
        "skills": supported_skills,
        "evidence_gaps": list(dict.fromkeys(evidence_gaps)),
        "strategy": generated.strategy,
    }


def _restore_required_metrics(
    source_bullets: list[str],
    source_item_id: str,
    bullets: list[str],
    evidence_ids: list[str],
    *,
    maximum_bullets: int | None,
) -> tuple[list[str], list[str]]:
    """Restore source bullets when a rewrite drops a protected metric or workload count."""
    def required_metrics(bullet: str) -> set[str]:
        return _operational_counts(bullet) | {
            normalize_metric(metric) for metric in extract_metrics(bullet)
            if _is_primary_metric(metric)
        }

    source_metrics = {
        metric
        for bullet in source_bullets
        for metric in required_metrics(bullet)
    }
    generated_metrics = {
        metric
        for bullet in bullets
        for metric in required_metrics(bullet)
    }
    missing = source_metrics - generated_metrics
    if not missing:
        return bullets, evidence_ids

    restored = list(bullets)
    restored_evidence = list(evidence_ids)
    source_candidates = [
        (index, bullet)
        for index, bullet in enumerate(source_bullets)
        if missing & required_metrics(bullet)
    ]
    for source_index, source_bullet in source_candidates:
        if not missing:
            break
        source_bullet_metrics = required_metrics(source_bullet)
        if not (missing & source_bullet_metrics):
            continue
        source_evidence_id = f"{source_item_id}:bullet:{source_index}"
        if source_bullet in restored:
            missing -= source_bullet_metrics
            continue
        if maximum_bullets is None or len(restored) < maximum_bullets:
            restored.append(source_bullet)
        else:
            replacement_index = next(
                (
                    index for index, bullet in enumerate(restored)
                    if not required_metrics(bullet)
                ),
                None,
            )
            if replacement_index is None:
                raise ValueError(
                    f"Unable to restore required metrics for {source_item_id} without "
                    "dropping a source-backed metric or operational count"
                )
            restored[replacement_index] = source_bullet
        restored_evidence.extend([source_item_id, source_evidence_id])
        missing -= source_bullet_metrics
    if missing:
        raise ValueError(
            f"Unable to restore required metrics for {source_item_id}: {sorted(missing)}"
        )
    return restored, list(dict.fromkeys(restored_evidence))


def _filter_skill_subset(
    cv: MasterCV,
    generated_skills: dict[str, list[str] | str],
) -> tuple[dict[str, list[str] | str], list[str]]:
    source_skills = {
        normalize_technology(skill)
        for values in cv.skills.values()
        for skill in ([values] if isinstance(values, str) else values)
    }
    source_texts = [cv.profile]
    for values in cv.skills.values():
        source_texts.extend([values] if isinstance(values, str) else values)
    for section in cv.sections:
        source_texts.append(section.title)
        for item in section.items:
            source_texts.extend((item.title, item.organization, item.location, item.dates))
            source_texts.extend(item.bullets)
    source_text = " ".join(source_texts)
    source_technologies = {
        normalize_technology(term) for term in extract_technologies(source_text)
    }
    supported: dict[str, list[str] | str] = {}
    unsupported: list[str] = []
    for group, values in generated_skills.items():
        generated_values = [values] if isinstance(values, str) else values
        approved = [
            skill for skill in generated_values
            if normalize_technology(skill) in source_skills
            or normalize_technology(skill) in source_technologies
            or _source_mentions_skill(skill, source_text)
        ]
        unsupported.extend(skill for skill in generated_values if skill not in approved)
        if approved:
            supported[group] = approved[0] if isinstance(values, str) else approved
    return supported, list(dict.fromkeys(unsupported))


def _validate_skill_subset(cv: MasterCV, generated_skills: dict[str, list[str] | str]) -> None:
    _, unsupported = _filter_skill_subset(cv, generated_skills)
    if unsupported:
        raise ValueError(f"Generated skills are not present in Master CV: {sorted(unsupported)}")


def _source_mentions_skill(skill: str, source_text: str) -> bool:
    parts = [part for part in re.split(r"[\s-]+", skill.strip()) if part]
    if not parts:
        return False
    pattern = r"(?<![\w])" + r"[\s-]*".join(re.escape(part) for part in parts)
    pattern += r"(?![\w+])"
    return re.search(pattern, source_text, re.IGNORECASE) is not None


def _deterministic_tailor(master_cv: dict[str, Any], jd_analysis: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(master_cv)
    sections = result.get("sections", [])
    priorities_by_role: dict[str, tuple[str, ...]] = {
        "ai_research": ("research", "publications", "projects", "experience", "education"),
        "systems_infra": ("experience", "projects", "skills", "education", "publications"),
        "data_engineering": ("experience", "projects", "skills", "education", "publications"),
        "general_software": ("experience", "projects", "skills", "education", "publications"),
        "quant_fintech": ("experience", "projects", "skills", "education", "publications"),
    }
    role_type = jd_analysis.get("role_type")
    priorities = priorities_by_role.get(str(role_type) if role_type is not None else "", ())
    rank = {name: index for index, name in enumerate(priorities)}
    section_rankings: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections):
        item_rankings: list[dict[str, Any]] = []
        for item_index, item in enumerate(section.get("items", [])):
            bullet_rankings = []
            for bullet_index, bullet in enumerate(item.get("bullets", [])):
                score, matched_terms = score_text_relevance(bullet, jd_analysis)
                bullet_rankings.append(
                    {
                        "text": bullet,
                        "original_index": bullet_index,
                        "score": score,
                        "matched_terms": matched_terms,
                    }
                )
            selected_bullets = sorted(
                bullet_rankings,
                key=lambda bullet: (-bullet["score"], bullet["original_index"]),
            )[:3]
            metadata = " ".join(
                str(item.get(key, ""))
                for key in ("title", "organization", "location")
            )
            metadata_score, _ = score_text_relevance(metadata, jd_analysis)
            item_score = metadata_score + sum(bullet["score"] for bullet in selected_bullets)
            item_id = item.get("source_item_id") or f"section:{section_index}:item:{item_index}"
            item["source_item_id"] = item_id
            item["bullets"] = [bullet["text"] for bullet in selected_bullets]
            item["evidence_ids"] = [
                f"{item_id}:bullet:{bullet['original_index']}"
                for bullet in selected_bullets
            ]
            item_rankings.append(
                {
                    "item": item,
                    "score": item_score,
                    "original_index": item_index,
                }
            )
        item_rankings.sort(key=lambda item: (-item["score"], item["original_index"]))
        section["items"] = [item["item"] for item in item_rankings]
        section_type = str(section.get("type", "")).lower()
        priority_index = rank.get(section_type, len(rank))
        priority_bonus = max(0, len(priorities) - priority_index) * 10
        section_rankings.append(
            {
                "section": section,
                "score": priority_bonus + sum(item["score"] for item in item_rankings),
                "original_index": section_index,
                "item_scores": {
                    item["item"]["source_item_id"]: item["score"] for item in item_rankings
                },
            }
        )
    section_rankings.sort(
        key=lambda section: (-section["score"], section["original_index"])
    )
    result["sections"] = [section["section"] for section in section_rankings]
    result["strategy"] = {
        "role_type": jd_analysis.get("role_type", "general_software"),
        "note": "Ranked by source evidence; configure DEEPSEEK_API_KEY for evidence-bound rewriting.",
        "section_scores": {
            section["section"]["type"]: section["score"] for section in section_rankings
        },
        "item_scores": {
            item_id: score
            for section in section_rankings
            for item_id, score in section["item_scores"].items()
        },
    }
    result["evidence_gaps"] = build_gap_analysis(master_cv, jd_analysis)["gaps"]
    return result


def _deterministic_cover(tailored_cv: TailoredResume, company_name: str) -> dict[str, Any]:
    evidence = [
        match.evidence[0]
        for match in tailored_cv.gap_analysis.evidence_matches
        if match.evidence
    ][:2]
    matched_terms = tailored_cv.gap_analysis.high_matches[:3]
    background = ", ".join(matched_terms) if matched_terms else "the experience in my resume"
    evidence_text = "; ".join(record.text for record in evidence)
    evidence_paragraph = (
        f"The documented work spans {evidence_text}."
        if evidence_text
        else "My enclosed resume presents the available evidence without overstating outcomes."
    )
    return {
        "salutation": "Dear Hiring Team,",
        "paragraphs": [
            f"My work in {background} connects directly to the technical challenges outlined for {company_name}, with an evidence-bound focus on measurable, reproducible delivery.",
            evidence_paragraph,
            f"I welcome a technical discussion about how this verified experience could support {company_name}.",
        ],
        "closing": f"Sincerely,\n{tailored_cv.name}",
        "evidence_ids": [record.evidence_id for record in evidence],
        "evidence_gaps": ["Configure DEEPSEEK_API_KEY for a fully tailored evidence-based draft."],
        "model_used": "deterministic_fallback",
    }
