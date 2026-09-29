from __future__ import annotations

from typing import Any

from .analysis import build_evidence_index
from .facts import build_fact_cards, unsupported_technology_terms
from .llm import LLMProvider
from .models import BulletPatch, validate_master_cv
from .tailoring import validate_truthfulness, verify_rewrite_fidelity
from .text_utils import normalize_sentence_ending
from .typography import evaluate_bullet_geometry


def _geometry(
    text: str, paragraph: dict[str, Any], target_lines: int = 2
) -> dict[str, Any]:
    return evaluate_bullet_geometry(
        text,
        paragraph["available_width_pt"],
        paragraph["font_name"],
        paragraph["font_size_pt"],
        target_lines=target_lines,
        bold=paragraph.get("bold", False),
    )


def _deviation(geometry: dict[str, Any], target_lines: int = 2) -> float:
    lines = geometry["estimated_lines"]
    if lines > target_lines:
        return (lines - target_lines) + 1.0
    if lines < target_lines:
        return 0.75
    if target_lines == 1:
        return 0.0 if geometry["last_line_ratio"] >= 0.5 else 0.2
    return max(0.0, 0.35 - geometry["last_line_ratio"], 0.25 if geometry["orphan_words"] else 0.0)


async def refine_one_bullet(
    tailored_cv: dict[str, Any],
    master_cv: dict[str, Any],
    source_item_map: dict[str, Any],
    layout_budget: dict[str, Any],
    provider: LLMProvider,
    *,
    page_overflow: bool = False,
    audit_only: bool = False,
    item_budgets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make at most one evidence-bound local patch; leave all other bullets untouched."""
    trace: dict[str, Any] = {"states": ["INGESTION", "PROJECTION", "GEOMETRIC_EVALUATION"]}
    paragraph_map = {entry["paragraph_id"]: entry for entry in layout_budget["paragraphs"]}
    budgets = item_budgets or {}
    ranked: list[
        tuple[float, dict[str, Any], int, dict[str, Any], dict[str, Any], int, str]
    ] = []
    for section_index, section in enumerate(tailored_cv.get("sections", [])):
        for item_index, item in enumerate(section.get("items", [])):
            item_id = item.get("source_item_id") or f"section:{section_index}:item:{item_index}"
            paragraph_ids = source_item_map.get(item_id, {}).get(
                "bullet_paragraph_ids", []
            )
            if not paragraph_ids:
                continue
            for index, bullet in enumerate(item.get("bullets", [])):
                paragraph = paragraph_map.get(paragraph_ids[min(index, len(paragraph_ids) - 1)])
                if paragraph is None:
                    continue
                tier = budgets.get(item_id, {}).get("tier")
                target_lines = 1 if tier == "tier_3" else 2
                geometry = _geometry(bullet, paragraph, target_lines)
                ranked.append((
                    _deviation(geometry, target_lines), item, index, paragraph, geometry,
                    target_lines, item_id,
                ))
    trace["evaluated_bullets"] = len(ranked)
    if not ranked:
        trace["outcome"] = "no_mapped_bullets"
        return trace
    deviation, item, index, paragraph, before, target_lines, item_id = max(
        ranked,
        key=(
            (lambda entry: (
                entry[4]["estimated_lines"] > 1,
                {"tier_3": 3, "tier_2": 2, "tier_1": 1}.get(
                    budgets.get(entry[6], {}).get("tier"), 1
                ),
                entry[4]["estimated_lines"],
                sum(entry[4]["line_widths_pt"]),
            ))
            if page_overflow else (lambda entry: entry[0])
        ),
    )
    trace["worst_bullet"] = {
        "source_item_id": item_id,
        "bullet_index": index,
        "target_lines": target_lines,
        "before": before,
    }
    if audit_only:
        trace["outcome"] = "evaluated_waiting_for_pdf"
        return trace
    if (deviation == 0 and not page_overflow) or not provider.available:
        trace["outcome"] = "within_budget" if deviation == 0 else "offline_no_patch"
        return trace

    trace["states"].append("TARGETED_RE_RANKING")
    original = item["bullets"][index]
    evidence = [
        record.text for record in build_evidence_index(master_cv)
        if record.evidence_id == item_id or record.evidence_id.startswith(f"{item_id}:bullet:")
    ]
    source = " ".join(evidence)
    cards = [card for card in build_fact_cards(master_cv)
             if card["evidence_id"].startswith(f"{item_id}:bullet:")]
    metrics = {metric for card in cards for metric in card["verified_metrics"]
               if metric.casefold() in original.casefold()}
    technologies = {technology for card in cards for technology in card["technologies"]
                    if technology.casefold() in original.casefold()}
    is_chinese = any("\u4e00" <= char <= "\u9fff" for char in original)
    if is_chinese:
        direction = (
            "精简约8-15个中文字符以减少实际PDF超页"
            if page_overflow else "改善中文表达流畅度，不增加未经验证的内容"
        )
    else:
        direction = (
            "shorten by about four English words to reduce actual PDF page overflow"
            if page_overflow else
            "shorten by about four English words" if before["estimated_lines"] > target_lines else
            "improve flow without adding unverified claims"
        )
    if before["orphan_words"]:
        direction += (
            "; avoid leaving 1-2 words on the final line by tightening the sentence, "
            "never by padding or inventing context"
        )
    if is_chinese:
        direction += "；保留证据支持的指标和技术名词，句末必须使用中文句号。"
        rewrite_instruction = "仅重写 CURRENT_BULLET 这一条。"
        ending_instruction = "以一个全角中文句号 。 结尾。"
    else:
        rewrite_instruction = "Rewrite ONLY the single CURRENT_BULLET."
        ending_instruction = "retain meaning and a final period."
    try:
        patch = await provider.complete_json(
            rewrite_instruction + " " + direction + ". Preserve every supplied verified "
            "metric and technology exactly, " + ending_instruction + " Return only {text: string}. "
            "Do not alter other bullets or add unsupported claims.",
            {
                "CURRENT_BULLET": original,
                "SOURCE_EVIDENCE": evidence,
                "REQUIRED_METRICS": sorted(metrics),
                "REQUIRED_TECHNOLOGIES": sorted(technologies),
                "FONT_GEOMETRY": paragraph,
                "GEOMETRY_BEFORE": before,
            },
            BulletPatch,
            temperature=0.1,
        )
    except (ValueError, RuntimeError):
        trace["outcome"] = "patch_request_failed"
        return trace
    candidate = normalize_sentence_ending(
        patch.text.strip(), "zh_CN" if is_chinese else "en"
    )
    after = _geometry(candidate, paragraph)
    trace["worst_bullet"]["after"] = after
    try:
        validate_truthfulness({"evidence": source}, {"text": candidate})
        if any(metric.casefold() not in candidate.casefold() for metric in metrics):
            raise ValueError("source metrics lost")
        if any(technology.casefold() not in candidate.casefold() for technology in technologies):
            raise ValueError("source technologies lost")
        if unsupported_technology_terms(source, candidate):
            raise ValueError("unverified technologies introduced")
        if item_id in budgets:
            findings = verify_rewrite_fidelity(
                validate_master_cv(master_cv),
                {"sections": [{"items": [{"source_item_id": item_id, "bullets": [candidate]}]}]},
                budgets,
            )
            if any(finding["restored_source_bullet"] for finding in findings):
                raise ValueError("Level 1 patch diverges from source")
        valid_ending = candidate.endswith("。") if is_chinese else candidate.endswith(".")
        if not valid_ending or "\ue000" <= candidate[-1] <= "\uf8ff":
            raise ValueError("invalid bullet punctuation")
        if page_overflow:
            if (after["estimated_lines"] > before["estimated_lines"] or
                    sum(after["line_widths_pt"]) >= sum(before["line_widths_pt"])):
                raise ValueError("page-overflow patch did not shorten the bullet")
        elif _deviation(after, target_lines) >= deviation:
            raise ValueError("geometry did not improve")
    except ValueError as error:
        trace["outcome"] = f"patch_rejected: {error}"
        return trace
    item["bullets"][index] = candidate
    trace["outcome"] = "patch_accepted"
    return trace