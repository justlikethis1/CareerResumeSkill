import pytest

from career_resume_skill.models import GeneratedTailoring, validate_master_cv
from career_resume_skill.tailoring import (
    _hydrate_generated_resume,
    _normalize_bullet_punctuation,
    _reject_unverified_company_claims,
    _remove_near_duplicate_bullets,
    _restore_required_metrics,
    _unsupported_technology_claims,
    _validate_skill_subset,
    validate_truthfulness,
    verify_rewrite_fidelity,
)


def test_preserves_supported_numeric_claim() -> None:
    validate_truthfulness({"metric": 38}, {"profile": "Reduced usage by 38."})


def test_rejects_unsupported_numeric_claim() -> None:
    with pytest.raises(ValueError, match="90"):
        validate_truthfulness({"metric": 38}, {"profile": "Reduced usage by 90%."})


@pytest.mark.parametrize("claim", [
    "Used sparse, long-chain feedback to optimize a DPO model.",
    "Applied long-horizon trajectory modeling to an ordinary forecast.",
])
def test_rejects_unsupported_rl_semantic_projection(claim: str) -> None:
    source = {"evidence": "Applied offline DPO and built a time-series passenger forecast."}

    with pytest.raises(ValueError, match="unsupported domain projections"):
        validate_truthfulness(source, {"profile": claim})


def test_technology_gate_accepts_hyphenation_variant_but_still_rejects_new_tool() -> None:
    assert _unsupported_technology_claims(
        "Evaluated the LSTMAttention model.",
        "Evaluated the LSTM-Attention model.",
    ) == set()
    assert _unsupported_technology_claims(
        "Evaluated the LSTMAttention model.",
        "Evaluated the LSTM-Attention model with Ray.",
    ) == {"ray"}


def test_technology_gate_accepts_contextual_random_forest_abbreviation() -> None:
    assert _unsupported_technology_claims(
        "Compared XGBoost/RF models.",
        "Compared XGBoost/Random Forest models.",
    ) == set()
    assert _unsupported_technology_claims(
        "Compared XGBoost/RF models.",
        "Compared XGBoost/Random Forest models with Ray.",
    ) == {"ray"}


def test_technology_gate_accepts_supported_multi_agent_and_llm_aliases() -> None:
    assert _unsupported_technology_claims(
        "Built a multi‑agent AI assistant using LLM‑driven reasoning.",
        "Built Multi-Agent Systems using LLM Reasoning.",
    ) == set()


def test_skill_subset_accepts_source_backed_experience_technologies() -> None:
    cv = validate_master_cv({
        "name": "Candidate",
        "contact": {"email": "test@example.com"},
        "sections": [{"type": "experience", "title": "Experience", "items": [{
            "title": "ML Engineer",
            "bullets": [
                (
                    "Used DPO and supervised finetuning with an XGBoost/RF + LSTMAttention model. "
                    "Built a multi‑agent AI assistant using LLM‑driven reasoning."
                )
            ],
        }]}],
        "skills": {"Languages": ["Python"]},
    })

    _validate_skill_subset(cv, {
        "AI/ML": [
            "DPO", "Supervised Fine-Tuning", "Random Forest", "LSTM-Attention",
            "Multi-Agent Systems", "LLM Reasoning",
        ]
    })


def test_hydration_caps_generated_bullets_to_item_budget() -> None:
    cv = validate_master_cv({
        "name": "Candidate",
        "contact": {"email": "test@example.com"},
        "sections": [{"type": "projects", "title": "Projects", "items": [{
            "source_item_id": "project-1",
            "title": "Project",
            "bullets": ["Built a Python service.", "Improved reliability."],
        }]}],
        "skills": {"Languages": ["Python"]},
    })
    generated = GeneratedTailoring.model_validate({
        "profile": "",
        "profile_evidence_ids": [],
        "sections": [{"type": "projects", "title": "Projects", "items": [{
            "source_item_id": "project-1",
            "bullets": [
                {"text": "Built a Python service.", "evidence_ids": ["project-1:bullet:0"]},
                {"text": "Improved reliability.", "evidence_ids": ["project-1:bullet:1"]},
            ],
        }]}],
        "skills": {},
        "evidence_gaps": [],
        "strategy": {},
    })

    result = _hydrate_generated_resume(cv, generated, {"project-1": {"bullets": 1}})

    assert result["sections"][0]["items"][0]["bullets"] == ["Built a Python service."]


def test_restore_required_metrics_replaces_metric_dropping_rewrite() -> None:
    bullets, evidence_ids = _restore_required_metrics(
        ["Used a 4-bit model and measured sub-10ms inference latency."],
        "project-1",
        ["Optimized model inference for production workloads."],
        ["project-1:bullet:0"],
        maximum_bullets=1,
    )

    assert bullets == ["Used a 4-bit model and measured sub-10ms inference latency."]
    assert set(evidence_ids) == {"project-1", "project-1:bullet:0"}


def test_near_duplicate_bullet_guard_keeps_distinct_sibling_axes() -> None:
    candidate = {"sections": [{"items": [{"bullets": [
        "Diagnosed out-of-domain degradation in multimodal models.",
        "Diagnosed out-of-domain degradation in multimodal models.",
        "Curated instruction data and tuned alignment hyperparameters.",
    ]}]}]}

    _remove_near_duplicate_bullets(candidate)

    assert candidate["sections"][0]["items"][0]["bullets"] == [
        "Diagnosed out-of-domain degradation in multimodal models.",
        "Curated instruction data and tuned alignment hyperparameters.",
    ]


@pytest.mark.parametrize(
    ("source", "generated"),
    [
        ("Observed 10⁻⁶ error.", "Observed 10⁻³ error."),
        ("Measured 1.2μs latency.", "Measured 1.2ms latency."),
        ("Handled 10000 QPS.", "Handled 10000 TPS."),
    ],
)
def test_rejects_changed_scientific_metrics_and_units(source: str, generated: str) -> None:
    with pytest.raises(ValueError, match="unsupported metrics"):
        validate_truthfulness({"evidence": source}, {"profile": generated})


def test_metric_comparison_ignores_whitespace_around_units() -> None:
    validate_truthfulness(
        {"evidence": "Measured 1.2 μs latency."},
        {"profile": "Measured 1.2μs latency."},
    )


def test_metric_comparison_normalizes_nonbreaking_sub_latency_hyphen() -> None:
    validate_truthfulness(
        {"evidence": "Measured sub‑10ms latency."},
        {"profile": "Measured sub-10ms latency."},
    )
    validate_truthfulness(
        {"evidence": "Measured sub‑10ms latency."},
        {"profile": "Measured sub -10ms latency."},
    )


def test_metric_comparison_accepts_equivalent_bit_depth_formatting() -> None:
    validate_truthfulness(
        {"evidence": "Used a 16bit SPI ADC."},
        {"profile": "Used a 16-bit SPI ADC."},
    )
    validate_truthfulness(
        {"evidence": "Used a 4‑bit quantized model."},
        {"profile": "Used a 4-bit quantized model."},
    )


def test_ignores_structural_single_digit_list_markers() -> None:
    validate_truthfulness({}, {"profile": "1. Built a verified project."})


def test_allows_date_formatting_when_year_is_source_supported() -> None:
    validate_truthfulness(
        {"experience": "Worked from September 2026 to June 2028."},
        {"experience": "09.2026--06.2028"},
    )


def test_bullet_punctuation_repairs_terminal_dash_without_changing_claim() -> None:
    candidate = {"sections": [{"items": [{"bullets": ["Improved latency by 12.5%—"]}]}]}

    _normalize_bullet_punctuation(candidate)

    assert candidate["sections"][0]["items"][0]["bullets"] == ["Improved latency by 12.5%."]


def test_level_specific_rewrite_fidelity_keeps_level_one_conservative() -> None:
    cv = validate_master_cv({
        "name": "Candidate", "contact": {"email": "test@example.com"},
        "sections": [{"type": "projects", "title": "Projects", "items": [{
            "title": "Calibration", "bullets": ["Measured sensor output with Python and reported error."],
        }]}],
    })
    item_id = "section:0:item:0"
    candidate = {"sections": [{"items": [{
        "source_item_id": item_id,
        "bullets": ["Measured sensor output with Python and reported error."],
    }]}]}

    level_one = {item_id: {"rewrite_intensity": "polish_only"}}
    assert verify_rewrite_fidelity(cv, candidate, level_one)[0]["word_overlap"] == 1.0

    candidate["sections"][0]["items"][0]["bullets"] = ["Deployed a Ray pipeline at scale."]
    findings = verify_rewrite_fidelity(cv, candidate, level_one)
    assert findings[0]["restored_source_bullet"] is True
    assert candidate["sections"][0]["items"][0]["bullets"] == cv.sections[0].items[0].bullets

    candidate["sections"][0]["items"][0]["bullets"] = cv.sections[0].items[0].bullets
    hero = {item_id: {"rewrite_intensity": "full_lexical_projection"}}
    assert verify_rewrite_fidelity(cv, candidate, hero)[0]["near_copy_warning"] is True


def test_company_claim_sandbox_flags_unsourced_recent_activity() -> None:
    with pytest.raises(ValueError, match="unverified company-specific claim"):
        _reject_unverified_company_claims([
            "Your company recently expanded its trading platform in Asia."
        ])
    _reject_unverified_company_claims([
        "The posted role requires reliable Python services; my verified work addresses that need."
    ])
