from career_resume_skill.ats import score_ats
from career_resume_skill.facts import (
    build_fact_cards,
    extract_hallucination_blacklist_terms,
    extract_metrics,
    extract_technologies,
    normalize_technology,
)
from career_resume_skill.text_utils import normalize_technology_casing


def test_casing_normalization_respects_source_and_symbol_boundaries() -> None:
    source = "PyTorch, C++, GitHub, SlimMCP and Model Context Protocol."
    generated = (
        "pytorch, PYTORCH, c++, c++20, github, slimmcp, model context protocol, "
        "tensorflow and mygithub."
    )
    assert normalize_technology_casing(generated, source) == (
        "PyTorch, PyTorch, C++, c++20, GitHub, SlimMCP, Model Context Protocol, "
        "tensorflow and mygithub."
    )


def test_ats_report_separates_exact_semantic_and_missing_terms() -> None:
    report = score_ats(
        {
            "must_haves": ["强化学习", "PPO"],
            "hard_skills": ["Python"],
            "nice_to_haves": ["Ray"],
            "ats_keywords": [],
        },
        "Applied RLHF/DPO preference alignment with Python.",
    )

    assert report["hard_requirements"]["exact_matches"] == ["Python"]
    assert report["hard_requirements"]["semantic_matches"] == {"强化学习": ["RLHF", "DPO"]}
    assert set(report["hard_requirements"]["missing"]) == {"PPO"}
    assert report["preferred_keywords"]["missing"] == ["Ray"]
    assert "not a prediction" in report["interpretation"]


def test_fact_cards_keep_evidence_ids_metrics_and_technologies() -> None:
    cv = {
        "name": "Candidate",
        "contact": {"email": "candidate@example.com"},
        "profile": "",
        "sections": [
            {
                "type": "experience",
                "title": "Experience",
                "items": [
                    {
                        "source_item_id": "exp-1",
                        "title": "ML Engineer",
                        "bullets": ["Improved PyTorch accuracy by 5.2% using DPO."],
                    }
                ],
            }
        ],
        "skills": {"Languages": ["Python"]},
    }

    cards = build_fact_cards(cv)
    bullet = next(card for card in cards if card["kind"] == "bullet")

    assert bullet["fact_id"] == "fact:exp-1:bullet:0"
    assert bullet["technologies"] == ["PyTorch", "DPO"]
    assert "5.2%" in bullet["verified_metrics"]


def test_fact_extraction_keeps_unicode_exponents_and_configured_technologies() -> None:
    cv = {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "sections": [{"type": "projects", "title": "Projects", "items": [{
            "title": "Training", "bullets": [
                (
                    "Trained 10⁶ samples with LoRA, QLoRA, vLLM, DeepSpeed, FSDP, Slurm, "
                    "Linux, Git, WandB and C++ with sub-10ms inference."
                )
            ],
        }]}],
    }
    card = next(card for card in build_fact_cards(cv) if card["kind"] == "bullet")

    assert {"10⁶", "sub-10ms"} <= set(card["verified_metrics"])
    assert {"lora", "qlora", "vllm", "deepspeed", "fsdp", "slurm", "linux", "git",
            "wandb", "c++"} <= extract_technologies(card["text"])


def test_fact_cards_preserve_scientific_notation_as_one_metric() -> None:
    cv = {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "sections": [{"type": "research", "title": "Research", "items": [{
            "title": "Precision", "bullets": ["Reduced error to 1e-6 with sub-10ms latency."]
        }]}],
    }

    bullet = next(card for card in build_fact_cards(cv) if card["kind"] == "bullet")
    assert {"1e-6", "sub-10ms"} <= set(bullet["verified_metrics"])


def test_extract_metrics_keeps_qps_throughput_and_unicode_powers() -> None:
    metrics = extract_metrics("Handled 12.5k QPS, 500 Mbps, 10⁶ events, 10⁻⁶ error, and 1e-6 latency.")

    assert any("QPS" in metric for metric in metrics)
    assert any("Mbps" in metric for metric in metrics)
    assert "10⁶" in metrics
    assert "10⁻⁶" in metrics
    assert "1e-6" in metrics


def test_extract_metrics_accepts_nonbreaking_sub_latency_hyphen() -> None:
    assert "sub‑10ms" in extract_metrics("Measured sub‑10ms latency.")
    assert "sub -10ms" in extract_metrics("Measured sub -10ms latency.")


def test_extract_metrics_keeps_bit_depth_as_a_compound_metric() -> None:
    assert "16bit" in extract_metrics("Used a 16bit SPI ADC.")
    assert "16-bit" in extract_metrics("Used a 16-bit SPI ADC.")
    assert "4‑bit" in extract_metrics("Used a 4‑bit quantized model.")


def test_extract_technologies_includes_sql_and_analytics_stack() -> None:
    technologies = extract_technologies("Built SQL dashboards in PostgreSQL, Tableau, and ClickHouse.")

    assert {"sql", "postgresql", "tableau", "clickhouse"} <= technologies


def test_technology_lexicon_covers_multiple_industry_stacks() -> None:
    technologies = extract_technologies(
        "Used TypeScript with React, Terraform on AWS, Databricks Delta Lake, "
        "QuantLib, OAuth 2.0, ROS 2, and GROMACS."
    )

    assert {
        "typescript", "react", "terraform", "aws", "databricks", "delta lake",
        "quantlib", "oauth 2.0", "ros 2", "gromacs",
    } <= technologies


def test_technology_lexicon_covers_business_operations_tools() -> None:
    technologies = extract_technologies(
        "Used SAP, Workday, Greenhouse, Salesforce, Zendesk, Toast POS, and Opera PMS."
    )

    assert {
        "sap", "workday", "greenhouse", "salesforce", "zendesk", "toast pos", "opera pms",
    } <= technologies


def test_technology_lexicon_covers_resume_modeling_and_alignment_terms() -> None:
    technologies = extract_technologies(
        "Used Random Forest with preference alignment and supervised fine tuning."
    )
    assert {
        "random forest", "preference alignment", "supervised fine tuning",
    } <= technologies
    assert "supervised finetuning" in extract_technologies("Applied supervised finetuning.")
    assert "random forest" in extract_technologies("Compared XGBoost/RF models.")


def test_technology_aliases_normalize_unicode_hyphens_and_resume_phrasing() -> None:
    technologies = extract_technologies(
        "Designed a multi‑agent assistant using LLM‑driven reasoning."
    )

    normalized = {normalize_technology(term) for term in technologies}
    assert {"multiagent", "llmreasoning"} <= normalized


def test_ats_accepts_supported_singular_pipeline_and_workflow_phrasing() -> None:
    report = score_ats(
        {
            "must_haves": ["reliable inference pipelines", "reproducible training workflows"],
            "hard_skills": [],
            "nice_to_haves": [],
            "ats_keywords": [],
        },
        "Built a reliable inference pipeline and reproducible training workflow.",
    )

    assert report["hard_requirements"]["missing"] == []


def test_ats_pipeline_aliases_are_bidirectional_for_phrase_variants() -> None:
    singular = score_ats(
        {"must_haves": ["training pipelines"], "hard_skills": [], "nice_to_haves": [], "ats_keywords": []},
        "Built a reproducible training pipeline.",
    )
    plural = score_ats(
        {"must_haves": ["reliable inference pipeline"], "hard_skills": [], "nice_to_haves": [], "ats_keywords": []},
        "Built reliable inference pipelines.",
    )

    assert singular["hard_requirements"]["missing"] == []
    assert plural["hard_requirements"]["missing"] == []


def test_hallucination_blacklist_does_not_flag_x_ray_as_ray_framework() -> None:
    assert extract_hallucination_blacklist_terms("X-ray image analysis") == set()
    assert extract_hallucination_blacklist_terms("Trained workloads with Ray workers") == {"ray"}
    assert extract_hallucination_blacklist_terms("Megatron-LM training") == {"megatron"}


def test_ats_filters_composite_chinese_requirements_even_for_direct_scoring() -> None:
    report = score_ats(
        {
            "must_haves": [
                "Python", "PyTorch", "长链路信用分配", "稀疏反馈",
                "熟练使用Python、PyTorch等语言和代码库",
            ],
            "hard_skills": [],
            "nice_to_haves": [],
            "ats_keywords": [],
        },
        "Python and PyTorch",
    )

    assert report["hard_requirements"]["total"] == 2
    assert report["hard_requirements"]["missing"] == []
