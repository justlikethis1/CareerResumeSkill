from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from .config import COVER_LETTER_HARD_MAX_WORDS, COVER_LETTER_HARD_MIN_WORDS

RoleType = Literal[
    "quant_fintech",
    "finance_operations",
    "systems_infra",
    "ai_research",
    "data_engineering",
    "hr_recruiting",
    "administration",
    "customer_service",
    "hospitality_food_service",
    "retail_sales",
    "general_software",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ContactInfo(StrictModel):
    email: str = Field(min_length=3)
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None


class ResumeItem(StrictModel):
    source_item_id: str | None = None
    title: str = Field(min_length=1)
    organization: str = ""
    location: str = ""
    dates: str = ""
    bullets: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("bullets")
    @classmethod
    def reject_empty_bullets(cls, bullets: list[str]) -> list[str]:
        if any(not bullet.strip() for bullet in bullets):
            raise ValueError("bullets must not contain empty strings")
        return bullets


class ResumeSection(StrictModel):
    type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    items: list[ResumeItem] = Field(default_factory=list)


class MasterCV(StrictModel):
    name: str = Field(min_length=1)
    contact: ContactInfo
    profile: str = ""
    sections: list[ResumeSection] = Field(default_factory=list)
    skills: dict[str, list[str] | str] = Field(default_factory=dict)


class EvidenceRecord(StrictModel):
    evidence_id: str
    kind: Literal["profile", "skill", "item", "bullet"]
    text: str
    section_type: str | None = None
    section_index: int | None = None
    item_index: int | None = None
    bullet_index: int | None = None


class RequirementEvidence(StrictModel):
    requirement: str
    evidence: list[EvidenceRecord] = Field(default_factory=list)


class GapAnalysis(StrictModel):
    match_score: int = Field(ge=0, le=100)
    high_matches: list[str]
    gaps: list[str]
    transferable_skills: list[str]
    evidence_matches: list[RequirementEvidence]


class GeneratedBullet(StrictModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class BulletPatch(StrictModel):
    text: str = Field(min_length=1)


class GeneratedResumeItem(StrictModel):
    source_item_id: str
    bullets: list[GeneratedBullet] = Field(min_length=1, max_length=4)


class GeneratedResumeSection(StrictModel):
    type: str
    title: str
    items: list[GeneratedResumeItem]


class GeneratedTailoring(StrictModel):
    profile: str
    profile_evidence_ids: list[str] = Field(default_factory=list)
    sections: list[GeneratedResumeSection]
    skills: dict[str, list[str] | str]
    evidence_gaps: list[str]
    strategy: dict[str, Any]


class TailoredResume(MasterCV):
    evidence_gaps: list[str] = Field(default_factory=list)
    strategy: dict[str, Any] = Field(default_factory=dict)
    gap_analysis: GapAnalysis
    model_used: str


class SemanticMappingDirective(StrictModel):
    source_domain: str
    target_lexicon: list[str] = Field(default_factory=list)
    engineering_angle: str
    expected_focus: str


class JDAnalysis(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    role_type: RoleType = "general_software"
    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    ats_keywords: list[str] = Field(default_factory=list)
    role_scores: dict[str, int] = Field(default_factory=dict)
    core_technical_pain_points: list[str] = Field(default_factory=list)
    semantic_mapping_strategy: list[str] = Field(default_factory=list)
    semantic_mapping_directives: list[SemanticMappingDirective] = Field(default_factory=list)
    model_used: str | None = None

    @field_validator("role_type", mode="before")
    @classmethod
    def migrate_legacy_role_type(cls, value: Any) -> Any:
        return {"ai_lab": "ai_research", "general_tech": "general_software"}.get(value, value)


class CoverLetterDraft(StrictModel):
    salutation: str
    paragraphs: list[str] = Field(
        description=(
            "Exactly three English prose paragraphs; target 50-70, 150-180, and 60-80 words. "
            "Validation bands are 45-80, 140-195, and 55-90 words respectively, with a "
            f"defensive {COVER_LETTER_HARD_MIN_WORDS}-{COVER_LETTER_HARD_MAX_WORDS} word total band."
        )
    )
    closing: str
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)

    @field_validator("paragraphs")
    @classmethod
    def require_three_paragraphs(cls, paragraphs: list[str]) -> list[str]:
        if len(paragraphs) != 3:
            raise ValueError("cover letter must contain exactly three paragraphs")
        return paragraphs

    @model_validator(mode="after")
    def enforce_word_budget(self, info: ValidationInfo) -> CoverLetterDraft:
        if (info.context or {}).get("allow_abbreviated_cover"):
            return self
        if getattr(self, "model_used", None) == "deterministic_fallback":
            return self
        counts = [len(paragraph.split()) for paragraph in self.paragraphs]
        bounds = ((45, 80), (140, 195), (55, 90))
        violations = [
            f"paragraph {index + 1}={count} (expected {minimum}-{maximum})"
            for index, (count, (minimum, maximum)) in enumerate(zip(counts, bounds))
            if not minimum <= count <= maximum
        ]
        total = sum(counts)
        if not COVER_LETTER_HARD_MIN_WORDS <= total <= COVER_LETTER_HARD_MAX_WORDS:
            violations.append(
                f"total={total} (expected {COVER_LETTER_HARD_MIN_WORDS}-{COVER_LETTER_HARD_MAX_WORDS})"
            )
        if violations:
            raise ValueError("cover letter word budget exceeded: " + "; ".join(violations))
        return self


class CoverLetter(CoverLetterDraft):
    model_used: str


def validate_master_cv(value: dict[str, Any] | MasterCV) -> MasterCV:
    return value if isinstance(value, MasterCV) else MasterCV.model_validate(value)


def validate_jd_analysis(value: dict[str, Any] | JDAnalysis) -> JDAnalysis:
    return value if isinstance(value, JDAnalysis) else JDAnalysis.model_validate(value)
