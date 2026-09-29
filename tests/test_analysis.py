import pytest
from pydantic import ValidationError

from career_resume_skill.analysis import (
    allocate_item_bullet_budgets,
    analyze_job_description_local,
    build_evidence_index,
    build_gap_analysis,
    filter_atomic_requirements,
)
from career_resume_skill.models import validate_master_cv


def _master_cv() -> dict[str, object]:
    return {
        "name": "Candidate",
        "contact": {"email": "candidate@example.com"},
        "profile": "",
        "sections": [],
        "skills": {"Languages": ["Python"]},
    }


def test_quant_role_and_gap_score_use_source_evidence() -> None:
    analysis = analyze_job_description_local(
        "Quant developer using Python, C++, low latency trading, and backtesting."
    )
    gap = build_gap_analysis(_master_cv(), analysis)

    assert analysis["role_type"] == "quant_fintech"
    assert gap["match_score"] == 25
    assert gap["gaps"] == ["C++", "Low Latency", "Backtesting"]
    assert gap["evidence_matches"][0]["evidence"][0]["evidence_id"] == "skill:Languages:0"


def test_ai_research_role() -> None:
    analysis = analyze_job_description_local(
        "AI Lab research role for PyTorch, CUDA, RLHF, and distributed training."
    )

    assert analysis["role_type"] == "ai_research"
    assert {"PyTorch", "CUDA", "RLHF", "Distributed Training"} <= set(
        analysis["must_haves"]
    )


@pytest.mark.parametrize(
    ("jd", "expected"),
    [
        ("Accounts payable, reconciliation, budgeting, and SAP reporting", "finance_operations"),
        ("Recruiter responsible for talent acquisition, onboarding, and Workday", "hr_recruiting"),
        ("Executive assistant handling calendar management and travel arrangements", "administration"),
        ("Customer support representative handling cases and complaint resolution", "customer_service"),
        ("Hotel front desk and restaurant food service with HACCP", "hospitality_food_service"),
        ("Retail sales associate managing merchandising and point of sale", "retail_sales"),
    ],
)
def test_local_role_classification_covers_non_technical_industries(jd: str, expected: str) -> None:
    assert analyze_job_description_local(jd)["role_type"] == expected


def test_filter_atomic_requirements_excludes_chinese_sentence_clauses() -> None:
    atomic, excluded = filter_atomic_requirements([
        "Python",
        "本科及以上学历，计算机科学、人工智能、数学、统计、电子工程等相关专业",
        "具备较强的工程实现、实验分析和问题定位能力，能够将算法方案转化为稳定可复现的训练流程",
    ])

    assert atomic == ["Python"]
    assert len(excluded) == 2


def test_chinese_agent_rl_jd_extracts_mixed_language_terms() -> None:
    analysis = analyze_job_description_local(
        "负责智能体强化学习长稳训练，研究 PPO、GRPO、RLHF、RLAIF、奖励模型和过程监督。"
    )

    assert analysis["role_type"] == "ai_research"
    assert {"PPO", "GRPO", "RLHF", "RLAIF", "智能体", "强化学习", "奖励模型"} <= set(
        analysis["must_haves"]
    )
    assert len(analysis["must_haves"]) == len(set(analysis["must_haves"]))


def test_master_cv_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="unexpected"):
        validate_master_cv({**_master_cv(), "unexpected": True})


def test_evidence_ids_are_stable_and_traceable() -> None:
    cv = _master_cv()
    cv["sections"] = [
        {
            "type": "projects",
            "title": "Projects",
            "items": [
                {
                    "title": "Engine",
                    "bullets": ["Built a low latency C++ engine."],
                }
            ],
        }
    ]

    evidence = build_evidence_index(cv)

    assert evidence[-1].evidence_id == "section:0:item:0:bullet:0"
    assert evidence[-1].text == "Built a low latency C++ engine."


def test_gap_analysis_maps_verified_domain_equivalents() -> None:
    cv = _master_cv()
    cv["sections"] = [
        {
            "type": "projects",
            "title": "Projects",
            "items": [
                {
                    "title": "Alignment",
                    "bullets": ["Applied RLHF/DPO preference alignment in a multi-agent system."],
                }
            ],
        }
    ]
    gap = build_gap_analysis(
        cv,
        {"role_type": "ai_research", "must_haves": ["强化学习", "智能体", "PPO"]},
    )

    assert gap["high_matches"] == ["强化学习", "智能体"]
    assert gap["gaps"] == ["PPO"]


def test_gap_analysis_maps_conservative_english_technology_aliases() -> None:
    cv = _master_cv()
    cv["sections"] = [{
        "type": "experience", "title": "Experience", "items": [{
            "title": "Platform Engineer",
            "bullets": ["Operated K8s workloads with Postgres and an LLM service."],
        }],
    }]

    gap = build_gap_analysis(cv, {
        "must_haves": ["Kubernetes", "PostgreSQL", "Large Language Model"],
        "role_type": "systems_infra",
    })

    assert gap["high_matches"] == ["Kubernetes", "PostgreSQL", "Large Language Model"]
    assert gap["gaps"] == []


def test_gap_analysis_maps_explicit_method_and_tool_abbreviations() -> None:
    cv = _master_cv()
    cv["sections"] = [{
        "type": "experience", "title": "Experience", "items": [{
            "title": "ML Engineer",
            "bullets": ["Used torch, TRT, Cpp20, DPO, SFT and RLHF."],
        }],
    }]

    gap = build_gap_analysis(cv, {
        "must_haves": [
            "PyTorch", "TensorRT", "C++", "Direct Preference Optimization",
            "Supervised Fine-Tuning", "Reinforcement Learning from Human Feedback",
        ],
    })

    assert gap["gaps"] == []


def test_dynamic_bullet_budgets_prioritize_relevant_items() -> None:
    cv = _master_cv()
    cv["sections"] = [
        {
            "type": "projects",
            "title": "Projects",
            "items": [
                {"title": "Alignment", "bullets": ["Applied RLHF and DPO alignment."]},
                {"title": "Backend", "bullets": ["Built a generic API."]},
                {"title": "Hardware", "bullets": ["Calibrated a sensor."]},
            ],
        }
    ]
    budgets = allocate_item_bullet_budgets(
        cv, {"must_haves": ["RLHF"], "nice_to_haves": [], "ats_keywords": ["DPO"]}
    )

    counts = [int(value["bullets"]) for value in budgets.values()]
    assert counts[0] == 2
    assert all(1 <= count <= 4 for count in counts)
    assert sum(counts) <= 11
    assert budgets["section:0:item:0"]["rewrite_intensity_level"] == 2
    assert budgets["section:0:item:0"]["rewrite_intensity"] == "strategic_re_anchoring"
    assert budgets["section:0:item:2"]["rewrite_intensity_level"] == 1
    assert budgets["section:0:item:2"]["rewrite_intensity"] == "polish_only"


def test_bullet_budget_caps_single_sparse_source_evidence() -> None:
    cv = _master_cv()
    cv["sections"] = [{"type": "experience", "title": "Experience", "items": [{
        "title": "Short role", "bullets": ["Handled customer requests."],
    }]}]

    budgets = allocate_item_bullet_budgets(
        cv, {"must_haves": ["customer service"], "role_type": "customer_service"}
    )

    assert budgets["section:0:item:0"]["bullets"] == 1


def test_hero_first_budget_keeps_top_items_in_tier_one_with_many_experiences() -> None:
    cv = _master_cv()
    cv["sections"] = [{
        "type": "experience",
        "title": "Experience",
        "items": [{
            "title": f"Experience {index}",
            "bullets": [f"Built a Python Kafka service for event processing {index}."]
        } for index in range(10)],
    }]

    budgets = allocate_item_bullet_budgets(
        cv, {"must_haves": ["Python", "Kafka"], "role_type": "systems_infra"}
    )

    ranked = list(budgets.values())
    assert ranked[0]["tier"] == "tier_1"
    assert ranked[0]["bullets"] == 3
    assert ranked[1]["tier"] == "tier_1"
    assert ranked[1]["bullets"] == 3
    assert sum(item["bullets"] for item in ranked) <= 11
    assert len(ranked) < 10


def test_ai_core_evidence_has_budget_floor_for_ai_systems_roles() -> None:
    cv = _master_cv()
    cv["sections"] = [{
        "type": "experience",
        "title": "Experience",
        "items": [
            {"title": "Forecasting Intern", "bullets": ["Built a forecasting model."]},
            {"title": "AI Algorithm Intern", "bullets": [
                "Applied RLHF and DPO preference alignment to multimodal models.",
            ]},
        ],
    }]

    budgets = allocate_item_bullet_budgets(
        cv,
        {
            "role_type": "systems_infra",
            "must_haves": ["Python", "reproducible training workflows"],
            "ats_keywords": ["inference", "reliable workflows"],
        },
    )

    ai_budget = budgets["section:0:item:1"]
    assert ai_budget["bullets"] >= 3
    assert ai_budget["tier"] == "tier_1"
