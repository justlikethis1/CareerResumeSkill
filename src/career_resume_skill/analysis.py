from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .models import EvidenceRecord, GapAnalysis, MasterCV, validate_master_cv

ROLE_SIGNALS: dict[str, tuple[str, ...]] = {
    "quant_fintech": (
        "quant",
        "fintech",
        "low latency",
        "trading",
        "backtesting",
        "c++",
        "market data",
        "risk",
        "低延迟",
        "量化",
        "交易",
    ),
    "finance_operations": (
        "finance operations", "financial analyst", "accounting", "accounts payable",
        "accounts receivable", "财务", "会计", "应收账款", "应付账款", "预算", "审计",
        "financial reporting", "reconciliation", "treasury", "compliance",
    ),
    "ai_research": (
        "llm",
        "large language model",
        "pytorch",
        "cuda",
        "rlhf",
        "dpo",
        "distributed training",
        "research",
        "大模型",
        "分布式训练",
        "算法",
        "强化学习",
        "智能体",
        "长稳训练",
        "后训练",
        "奖励模型",
        "过程监督",
        "环境交互",
        "多模态",
    ),
    "systems_infra": (
        "distributed systems",
        "infrastructure",
        "throughput",
        "scalability",
        "kubernetes",
        "microservices",
        "memory optimization",
        "concurrency",
        "分布式系统",
        "基础设施",
        "高并发",
        "吞吐量",
    ),
    "data_engineering": (
        "data engineering",
        "data pipeline",
        "etl",
        "spark",
        "kafka",
        "data warehouse",
        "airflow",
        "数据工程",
        "数据管道",
        "数据仓库",
    ),
    "hr_recruiting": (
        "human resources", "human resource", "recruiter", "recruiting", "talent acquisition",
        "people operations", "人力资源", "招聘", "人才招聘", "员工关系", "薪酬", "绩效",
        "onboarding", "employee relations", "applicant tracking",
    ),
    "administration": (
        "administrative assistant", "office administrator", "executive assistant", "operations coordinator",
        "行政", "行政助理", "办公室管理", "文员", "运营协调", "calendar management", "travel arrangement",
    ),
    "customer_service": (
        "customer service", "customer support", "call center", "contact center", "客服", "客户服务",
        "客户支持", "呼叫中心", "case management", "complaint resolution", "service desk",
    ),
    "hospitality_food_service": (
        "hospitality", "hotel", "restaurant", "food service", "front desk", "housekeeping",
        "餐饮", "酒店", "前台", "客房", "餐厅", "服务员", "food safety", "food preparation",
    ),
    "retail_sales": (
        "retail", "sales associate", "account executive", "business development", "store manager",
        "零售", "销售", "导购", "门店", "客户开发", "merchandising", "point of sale",
    ),
    "general_software": (
        "software engineer",
        "backend",
        "full stack",
        "rest api",
        "product",
        "后端",
        "软件工程",
        "全栈",
    ),
}

MUST_HAVE_TERMS = (
    "Python",
    "C++",
    "C++20",
    "PyTorch",
    "CUDA",
    "TensorRT",
    "SFT",
    "RLHF",
    "DPO",
    "Distributed Training",
    "Low Latency",
    "Backtesting",
    "Vector Database",
    "Mixed Precision",
    "Inference Latency",
    "PPO",
    "GRPO",
    "RLAIF",
    "Reward Modeling",
    "Process Supervision",
    "Agent",
    "Reinforcement Learning",
    "强化学习",
    "智能体",
    "大模型",
    "长稳训练",
    "奖励模型",
    "过程监督",
    "环境评价器",
    "轨迹筛选",
    "Kubernetes",
    "Kafka",
    "Spark",
    "Airflow",
    "Microservices",
    "Concurrency",
    "Throughput",
    "Scalability",
    "ETL",
    "Accounting", "Accounts Payable", "Accounts Receivable", "Financial Reporting",
    "Reconciliation", "Budgeting", "Audit", "Compliance", "财务", "会计", "审计",
    "Recruiting", "Talent Acquisition", "Human Resources", "Onboarding", "Employee Relations",
    "招聘", "人力资源", "员工关系", "绩效", "Applicant Tracking",
    "Calendar Management", "Office Administration", "行政", "行政助理", "办公室管理",
    "Customer Service", "Customer Support", "Call Center", "Complaint Resolution", "Service Desk",
    "客户服务", "客户支持", "呼叫中心", "投诉处理",
    "Hospitality", "Food Service", "Front Desk", "Housekeeping", "Food Safety",
    "餐饮", "酒店", "前台", "客房", "食品安全",
    "Retail", "Sales", "Business Development", "Store Management", "Merchandising",
    "零售", "销售", "门店", "客户开发",
)

NICE_TO_HAVE_TERMS = (
    "NeurIPS",
    "ICLR",
    "ACL",
    "KDD",
    "Kaggle",
    "Open Source",
    "GitHub Stars",
    "CPA", "CFA", "ACCA", "SHRM", "CIPD", "PMP", "Six Sigma", "食品安全证书",
)

REQUIREMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "强化学习": ("RLHF", "DPO", "reinforcement learning"),
    "智能体": ("agent", "multi-agent", "智能体"),
    "大模型": ("large language model", "LLM", "multimodal model", "多模态模型"),
    "奖励建模": ("reward modeling", "reward model", "奖励模型"),
    "奖励模型": ("reward modeling", "reward model", "奖励建模"),
    "过程监督": ("process supervision", "过程监督"),
    "Kubernetes": ("K8s",),
    "K8s": ("Kubernetes",),
    "PostgreSQL": ("Postgres",),
    "Postgres": ("PostgreSQL",),
    "Reinforcement Learning": ("RL",),
    "RL": ("Reinforcement Learning",),
    "Large Language Model": ("LLM", "LLMs", "foundation model"),
    "LLM": ("large language model", "foundation model"),
    "Low Latency": ("ultra-low latency", "sub-millisecond latency", "低延迟"),
    "C++": ("Cpp", "Cpp20", "C plus plus"),
    "Cpp": ("C++",),
    "PyTorch": ("torch",),
    "torch": ("PyTorch",),
    "TensorRT": ("TRT",),
    "TRT": ("TensorRT",),
    "Direct Preference Optimization": ("DPO",),
    "DPO": ("Direct Preference Optimization",),
    "Supervised Fine-Tuning": ("SFT", "supervised fine tuning"),
    "SFT": ("supervised fine-tuning", "supervised fine tuning"),
    "Reinforcement Learning from Human Feedback": ("RLHF",),
    "RLHF": ("reinforcement learning from human feedback",),
    "reliable inference pipelines": ("reliable inference pipeline",),
    "reproducible training workflows": ("reproducible training workflow",),
}


def _contains(text: str, term: str) -> bool:
    if any("\u4e00" <= character <= "\u9fff" for character in term):
        return term.casefold() in text.casefold()
    return re.search(
        rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.IGNORECASE
    ) is not None


def extract_terms(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if _contains(text, term)]


def is_non_atomic_requirement(term: str) -> bool:
    normalized = re.sub(r"[\s-]+", "", term.casefold().strip())
    known_atomic = {
        re.sub(r"[\s-]+", "", candidate.casefold())
        for candidate in (*MUST_HAVE_TERMS, *REQUIREMENT_ALIASES.keys())
        if any("\u4e00" <= character <= "\u9fff" for character in candidate)
    }
    cjk_characters = sum("\u4e00" <= character <= "\u9fff" for character in term)
    clause_marks = sum(character in "，,；;。、" for character in term)
    return (
        normalized not in known_atomic
        and (
            "等" in term
            or cjk_characters >= 12
            or (cjk_characters >= 4 and clause_marks >= 1)
            or cjk_characters >= 4
        )
    )


def filter_atomic_requirements(terms: Iterable[str]) -> tuple[list[str], list[str]]:
    atomic: list[str] = []
    excluded: list[str] = []
    seen: set[str] = set()
    for raw_term in terms:
        term = str(raw_term).strip()
        if not term or term.casefold() in seen:
            continue
        seen.add(term.casefold())
        (excluded if is_non_atomic_requirement(term) else atomic).append(term)
    return atomic, excluded


def classify_role(jd_text: str) -> tuple[str, dict[str, int]]:
    scores = {
        role: sum(1 for signal in signals if _contains(jd_text, signal))
        for role, signals in ROLE_SIGNALS.items()
    }
    role_type = max(scores, key=scores.get)
    if scores[role_type] == 0:
        role_type = "general_software"
    return role_type, scores


def analyze_job_description_local(jd_text: str) -> dict[str, Any]:
    role_type, role_scores = classify_role(jd_text)
    must_haves = list(dict.fromkeys(extract_terms(jd_text, MUST_HAVE_TERMS)))
    nice_to_haves = list(dict.fromkeys(extract_terms(jd_text, NICE_TO_HAVE_TERMS)))
    return {
        "role_type": role_type,
        "role_scores": role_scores,
        "must_haves": must_haves,
        "nice_to_haves": nice_to_haves,
        "ats_keywords": list(dict.fromkeys(must_haves + nice_to_haves)),
        "excluded_non_atomic_requirements": [],
    }


def build_evidence_index(master_cv: dict[str, Any] | MasterCV) -> list[EvidenceRecord]:
    cv = validate_master_cv(master_cv)
    records: list[EvidenceRecord] = []
    if cv.profile:
        records.append(EvidenceRecord(evidence_id="profile", kind="profile", text=cv.profile))
    for group, values in cv.skills.items():
        skill_values = [values] if isinstance(values, str) else values
        for skill_index, skill in enumerate(skill_values):
            records.append(
                EvidenceRecord(
                    evidence_id=f"skill:{group}:{skill_index}",
                    kind="skill",
                    text=skill,
                )
            )
    for section_index, section in enumerate(cv.sections):
        for item_index, item in enumerate(section.items):
            item_id = item.source_item_id or f"section:{section_index}:item:{item_index}"
            item_text = " | ".join(
                value
                for value in (item.title, item.organization, item.location, item.dates)
                if value
            )
            records.append(
                EvidenceRecord(
                    evidence_id=item_id,
                    kind="item",
                    text=item_text,
                    section_type=section.type,
                    section_index=section_index,
                    item_index=item_index,
                )
            )
            for bullet_index, bullet in enumerate(item.bullets):
                records.append(
                    EvidenceRecord(
                        evidence_id=(
                            f"{item_id}:bullet:{bullet_index}"
                        ),
                        kind="bullet",
                        text=bullet,
                        section_type=section.type,
                        section_index=section_index,
                        item_index=item_index,
                        bullet_index=bullet_index,
                    )
                )
    return records


def build_gap_analysis(
    master_cv: dict[str, Any] | MasterCV, jd_analysis: dict[str, Any]
) -> dict[str, Any]:
    cv = validate_master_cv(master_cv)
    evidence_index = build_evidence_index(cv)
    cv_text = " ".join(record.text for record in evidence_index)
    requirements = jd_analysis.get("must_haves", [])
    evidence_matches = [
        {
            "requirement": term,
            "evidence": [
                record.model_dump()
                for record in evidence_index
                if any(
                    _contains(record.text, candidate)
                    for candidate in (term, *REQUIREMENT_ALIASES.get(term, ()))
                )
            ],
        }
        for term in requirements
    ]
    matched = [match["requirement"] for match in evidence_matches if match["evidence"]]
    missing = [term for term in requirements if term not in matched]
    score = round(100 * len(matched) / len(requirements)) if requirements else 0
    return GapAnalysis.model_validate(
        {
        "match_score": score,
        "high_matches": matched,
        "gaps": missing,
        "transferable_skills": _transferable_skills(cv_text, jd_analysis.get("role_type")),
            "evidence_matches": evidence_matches,
        }
    ).model_dump()


def score_text_relevance(text: str, jd_analysis: dict[str, Any]) -> tuple[int, list[str]]:
    weighted_terms = (
        [(term, 5) for term in jd_analysis.get("must_haves", [])]
        + [(term, 2) for term in jd_analysis.get("nice_to_haves", [])]
        + [(term, 1) for term in jd_analysis.get("ats_keywords", [])]
    )
    matched_weights: dict[str, int] = {}
    canonical_terms: dict[str, str] = {}
    for term, weight in weighted_terms:
        key = str(term).casefold()
        canonical_terms.setdefault(key, str(term))
        matched_weights[key] = max(matched_weights.get(key, 0), weight)
    matched = [key for key in matched_weights if _contains(text, canonical_terms[key])]
    return sum(matched_weights[key] for key in matched), [canonical_terms[key] for key in matched]


def _is_ai_systems_target(jd_analysis: dict[str, Any]) -> bool:
    role_type = str(jd_analysis.get("role_type", "")).casefold()
    target_text = " ".join(_flatten_strings(jd_analysis)).casefold()
    return role_type in {"ai_research", "systems_infra"} or any(
        _contains(target_text, term)
        for term in (
            "ai",
            "machine learning",
            "large language model",
            "llm",
            "inference",
            "training workflow",
            "reproducible",
            "大模型",
            "后训练",
            "推理",
        )
    )


def _is_ai_core_evidence(text: str) -> bool:
    return any(
        _contains(text, term)
        for term in (
            "llm",
            "large language model",
            "multimodal",
            "post-training",
            "post training",
            "rlhf",
            "dpo",
            "sft",
            "alignment",
            "大模型",
            "多模态",
            "后训练",
            "对齐",
        )
    )


def allocate_item_bullet_budgets(
    master_cv: dict[str, Any] | MasterCV,
    jd_analysis: dict[str, Any],
    total_limit: int = 11,
) -> dict[str, dict[str, int | str | list[dict[str, Any]]]]:
    cv = validate_master_cv(master_cv)
    ranked: list[tuple[int, int, str, int, bool]] = []
    order = 0
    for section_index, section in enumerate(cv.sections):
        for item_index, item in enumerate(section.items):
            if not item.bullets:
                continue
            item_id = item.source_item_id or f"section:{section_index}:item:{item_index}"
            score, _ = score_text_relevance(
                " ".join([item.title, item.organization, *item.bullets]), jd_analysis
            )
            evidence_words = len(re.findall(r"\b\w+\b", " ".join(item.bullets)))
            evidence_cap = 2 if evidence_words < 8 else 3 if len(item.bullets) < 2 else 4
            ai_core = _is_ai_systems_target(jd_analysis) and _is_ai_core_evidence(
                " ".join([item.title, item.organization, *item.bullets])
            )
            ranked.append((score, order, item_id, evidence_cap, ai_core))
            order += 1
    ranked.sort(key=lambda entry: (not entry[4], -entry[0], entry[1]))
    budgets: dict[str, dict[str, int | str | list[dict[str, Any]]]] = {}
    remaining = max(0, total_limit)
    for rank, (score, _, item_id, evidence_cap, ai_core) in enumerate(ranked):
        if remaining <= 0:
            break
        desired = (
            4 if rank == 0 and score > 0 else
            3 if rank == 1 and score > 0 else
            2 if rank < 4 and score > 0 else
            1
        )
        if ai_core:
            desired = max(desired, 3)
        bullet_count = min(desired, evidence_cap, remaining)
        tier = "tier_1" if bullet_count >= 3 else "tier_2" if bullet_count == 2 else "tier_3"
        intensity = {"tier_1": (3, "full_lexical_projection"),
                     "tier_2": (2, "strategic_re_anchoring"),
                     "tier_3": (1, "polish_only")}[tier]
        budgets[item_id] = {
            "bullets": bullet_count,
            "tier": tier,
            "relevance_score": score,
            "rewrite_intensity_level": intensity[0],
            "rewrite_intensity": intensity[1],
        }
        remaining -= bullet_count
        if remaining == 0:
            break
    return budgets


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _flatten_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _flatten_strings(child)]
    return []


def _transferable_skills(cv_text: str, role_type: str | None) -> list[str]:
    candidates = {
        "quant_fintech": ("Python", "C++", "statistics", "optimization", "distributed systems"),
        "finance_operations": ("financial reporting", "accounting", "reconciliation", "compliance", "Excel"),
        "ai_research": ("Python", "research", "experimentation", "distributed systems", "optimization"),
        "systems_infra": ("Python", "C++", "distributed systems", "optimization"),
        "data_engineering": ("Python", "distributed systems", "optimization"),
        "hr_recruiting": ("recruiting", "communication", "employee relations", "onboarding"),
        "administration": ("office administration", "calendar management", "coordination", "communication"),
        "customer_service": ("customer service", "communication", "case management", "complaint resolution"),
        "hospitality_food_service": ("hospitality", "customer service", "food safety", "teamwork"),
        "retail_sales": ("sales", "customer service", "merchandising", "business development"),
    }.get(role_type, ("communication", "customer service", "coordination", "problem solving"))
    return [term for term in candidates if _contains(cv_text, term)]
