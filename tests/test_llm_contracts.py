import asyncio
import json
from types import SimpleNamespace

import pytest

from career_resume_skill.config import Settings
from career_resume_skill.few_shots import cover_exemplar, resume_exemplars, validate_exemplars
from career_resume_skill.llm import DeepSeekClient, _repair_guidance
from career_resume_skill.models import CoverLetterDraft, GeneratedTailoring, validate_master_cv
from career_resume_skill.tailoring import _hydrate_generated_resume, draft_cover, tailor_resume


class _Completions:
    def __init__(self, contents: list[str]) -> None:
        self.contents = iter(contents)
        self.calls = 0
        self.call_arguments: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        self.call_arguments.append(kwargs)
        content = next(self.contents)
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeOpenAI:
    def __init__(self, contents: list[str]) -> None:
        self.chat = SimpleNamespace(completions=_Completions(contents))


def _valid_cover_paragraphs() -> list[str]:
    return [" ".join(
        " ".join([word] * min(15, count - index)) + "."
        for index in range(0, count, 15)
    ) for word, count in (("Opening", 55), ("Evidence", 155), ("Alignment", 65))]


def test_complete_json_repairs_invalid_schema_once() -> None:
    client = DeepSeekClient(Settings(api_key="test"))
    fake = _FakeOpenAI(
        [
            '{"salutation":"Hi"}',
            json.dumps(
                {
                    "salutation": "Dear Team,",
                    "paragraphs": _valid_cover_paragraphs(),
                    "closing": "Regards",
                    "evidence_ids": [],
                    "evidence_gaps": [],
                }
            ),
        ]
    )
    client._client = fake  # type: ignore[assignment]

    result = asyncio.run(client.complete_json("draft", {}, CoverLetterDraft))

    assert result.paragraphs == _valid_cover_paragraphs()
    assert fake.chat.completions.calls == 2
    assert fake.chat.completions.call_arguments[0]["temperature"] == 0.2
    assert fake.chat.completions.call_arguments[1]["temperature"] == 0.1
    assert fake.chat.completions.call_arguments[0]["top_p"] > fake.chat.completions.call_arguments[1]["top_p"]


def test_complete_json_retries_empty_response_with_bounded_repair_context() -> None:
    client = DeepSeekClient(Settings(api_key="test"))
    fake = _FakeOpenAI([
        "",
        json.dumps({
            "salutation": "Dear Team,",
            "paragraphs": _valid_cover_paragraphs(),
            "closing": "Regards",
            "evidence_ids": [],
            "evidence_gaps": [],
        }),
    ])
    client._client = fake  # type: ignore[assignment]

    result = asyncio.run(client.complete_json("draft", {}, CoverLetterDraft))

    assert result.paragraphs == _valid_cover_paragraphs()
    assert fake.chat.completions.calls == 2


def test_complete_json_allows_bounded_extra_repairs_for_cover_letter_word_budget() -> None:
    short = {
        "salutation": "Dear Team,", "paragraphs": ["One", "Two", "Three"],
        "closing": "Regards", "evidence_ids": [], "evidence_gaps": [],
    }
    valid = {
        "salutation": "Dear Team,", "paragraphs": _valid_cover_paragraphs(),
        "closing": "Regards", "evidence_ids": [], "evidence_gaps": [],
    }
    client = DeepSeekClient(Settings(api_key="test"))
    fake = _FakeOpenAI([
        json.dumps(short),
        json.dumps(short),
        json.dumps(valid),
    ])
    client._client = fake  # type: ignore[assignment]

    result = asyncio.run(client.complete_json("draft", {}, CoverLetterDraft))

    assert result.paragraphs == _valid_cover_paragraphs()
    assert fake.chat.completions.calls == 3


def test_cover_letter_model_enforces_word_budget() -> None:
    CoverLetterDraft.model_validate({
        "salutation": "Dear Team,", "paragraphs": _valid_cover_paragraphs(),
        "closing": "Regards",
    })
    with pytest.raises(ValueError, match="word budget exceeded"):
        CoverLetterDraft.model_validate({
            "salutation": "Dear Team,", "paragraphs": ["One", "Two", "Three"],
            "closing": "Regards",
        })


def test_cover_letter_model_accepts_structurally_valid_defensive_underflow() -> None:
    paragraphs = [
        " ".join(["Opening"] * 55),
        " ".join(["Evidence"] * 155),
        " ".join(["Alignment"] * 57),
    ]

    result = CoverLetterDraft.model_validate({
        "salutation": "Dear Team,",
        "paragraphs": paragraphs,
        "closing": "Regards",
    })

    assert sum(len(paragraph.split()) for paragraph in result.paragraphs) == 267


def test_repair_guidance_preserves_metrics_on_overflow() -> None:
    guidance = _repair_guidance(ValueError("WordCountOverflow: 340 word maximum exceeded"))

    assert "shorten only decorative adjectives/adverbs" in guidance
    assert "preserve all numbers, metrics, proper nouns, technologies" in guidance


def test_few_shots_do_not_contain_trailing_dash_fillers() -> None:
    examples = resume_exemplars("ai_research")
    assert "---" not in examples


def test_repair_guidance_expands_cover_letter_underflow_from_evidence_only() -> None:
    guidance = _repair_guidance(ValueError(
        "cover letter word budget exceeded: paragraph 3=47 (expected 55-90); "
        "total=200 (expected 210-350)"
    ))

    assert "DO NOT SHORTEN" in guidance
    assert "paragraph 3: add at least 18 words" in guidance
    assert "total: add at least 20 words" in guidance
    assert "add distinct technical detail supported by the cited evidence" in guidance.casefold()
    assert "Do not invent claims or metrics" in guidance


def test_repair_guidance_leaves_word_count_margin_after_live_underflow() -> None:
    guidance = _repair_guidance(ValueError(
        "cover letter word budget exceeded: paragraph 2=107 (expected 115-195); "
        "total=212 (expected 210-350)"
    ))

    assert "paragraph 2: add at least 18 words" in guidance
    assert "10-word safety margin" in guidance
    assert "do not repeat claims or metrics already used in another paragraph" in guidance.casefold()


def test_cover_letter_second_paragraph_allows_concise_evidence_without_padding() -> None:
    paragraphs = _valid_cover_paragraphs()
    paragraphs[1] = " ".join(["Evidence"] * 139)
    CoverLetterDraft.model_validate({
        "salutation": "Dear Team,", "paragraphs": paragraphs, "closing": "Sincerely",
    })
    paragraphs[1] = " ".join(["Evidence"] * 115)
    CoverLetterDraft.model_validate({
        "salutation": "Dear Team,", "paragraphs": paragraphs, "closing": "Sincerely",
    })
    paragraphs[1] = " ".join(["Evidence"] * 114)
    with pytest.raises(ValueError, match="paragraph 2=114 \\(expected 115-195\\)"):
        CoverLetterDraft.model_validate({
            "salutation": "Dear Team,", "paragraphs": paragraphs, "closing": "Sincerely",
        })


def test_cover_letter_total_budget_tolerates_small_generation_variance() -> None:
    paragraphs = [
        " ".join(["Opening"] * 55),
        " ".join(["Evidence"] * 115),
        " ".join(["Alignment"] * 50),
    ]
    CoverLetterDraft.model_validate({
        "salutation": "Dear Team,", "paragraphs": paragraphs, "closing": "Sincerely",
    })

    paragraphs = [
        " ".join(["Opening"] * 45),
        " ".join(["Evidence"] * 120),
        " ".join(["Alignment"] * 55),
    ]
    result = CoverLetterDraft.model_validate({
        "salutation": "Dear Team,", "paragraphs": paragraphs, "closing": "Sincerely",
    })
    assert sum(len(paragraph.split()) for paragraph in result.paragraphs) == 220


def test_repair_guidance_restores_missing_metrics_without_invention() -> None:
    guidance = _repair_guidance(ValueError("MissingMetrics: source values absent from output"))

    assert "restore every omitted source metric verbatim" in guidance
    assert "do not round, reinterpret, or invent values" in guidance


def test_unknown_evidence_reference_is_rejected() -> None:
    cv = validate_master_cv(
        {
            "name": "Candidate",
            "contact": {"email": "candidate@example.com"},
            "profile": "Python engineer",
            "sections": [
                {
                    "type": "projects",
                    "title": "Projects",
                    "items": [{"title": "Engine", "bullets": ["Built an engine."]}],
                }
            ],
            "skills": {"Languages": ["Python"]},
        }
    )
    generated = GeneratedTailoring.model_validate(
        {
            "profile": "Python engineer",
            "profile_evidence_ids": ["profile"],
            "sections": [
                {
                    "type": "projects",
                    "title": "Projects",
                    "items": [
                        {
                            "source_item_id": "section:0:item:0",
                            "bullets": [
                                {
                                    "text": "Built an engine.",
                                    "evidence_ids": ["invented:evidence"],
                                }
                            ],
                        }
                    ],
                }
            ],
            "skills": {"Languages": ["Python"]},
            "evidence_gaps": [],
            "strategy": {},
        }
    )

    with pytest.raises(ValueError, match="Unknown evidence IDs"):
        _hydrate_generated_resume(cv, generated)


def test_hydration_merges_same_type_sections_in_master_order() -> None:
    cv = validate_master_cv({
        "name": "Candidate",
        "contact": {"email": "candidate@example.com"},
        "sections": [
            {"type": "experience", "title": "Experience", "items": [
                {"source_item_id": "exp-1", "title": "First", "bullets": ["Built Python systems."]},
            ]},
            {"type": "projects", "title": "Projects", "items": [
                {"source_item_id": "project-1", "title": "Project", "bullets": ["Built APIs."]},
            ]},
            {"type": "experience", "title": "Experience", "items": [
                {"source_item_id": "exp-2", "title": "Second", "bullets": ["Analyzed data."]},
            ]},
        ],
        "skills": {},
    })
    generated = GeneratedTailoring.model_validate({
        "profile": "", "profile_evidence_ids": [],
        "sections": [
            {"type": "experience", "title": "Experience", "items": [{
                "source_item_id": "exp-2",
                "bullets": [{"text": "Analyzed data.", "evidence_ids": ["exp-2:bullet:0"]}],
            }]},
            {"type": "projects", "title": "Projects", "items": [{
                "source_item_id": "project-1",
                "bullets": [{"text": "Built APIs.", "evidence_ids": ["project-1:bullet:0"]}],
            }]},
            {"type": "experience", "title": "Experience", "items": [{
                "source_item_id": "exp-1",
                "bullets": [{"text": "Built Python systems.", "evidence_ids": ["exp-1:bullet:0"]}],
            }]},
        ],
        "skills": {}, "evidence_gaps": [], "strategy": {},
    })

    result = _hydrate_generated_resume(cv, generated)

    assert [section["type"] for section in result["sections"]] == ["experience", "projects"]
    assert [item["source_item_id"] for item in result["sections"][0]["items"]] == ["exp-2", "exp-1"]


def test_cover_letter_company_policy_uses_only_supplied_context() -> None:
    class Offline:
        available = False
        model_name = "offline"

    class Capture:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.policies = []
            self.tasks = []

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.policies.append(payload["COMPANY_CLAIM_POLICY"])
            self.tasks.append(task)
            return response_model.model_validate({
                "salutation": "Dear Team,", "paragraphs": _valid_cover_paragraphs(),
                "closing": "Regards", "evidence_ids": ["skill:Languages:0"], "evidence_gaps": [],
            })

    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [], "skills": {"Languages": ["Python"]}}
    tailored = asyncio.run(tailor_resume(cv, {}, Offline()))
    provider = Capture()

    asyncio.run(draft_cover(tailored, "Example Co", "professional", provider))
    asyncio.run(draft_cover(
        tailored, "Example Co", "professional", provider,
        verified_company_context="Published role description from Example Co",
    ))

    assert provider.policies == ["jd_only", "verified_context_only"]
    assert "SYNTHETIC COVER LETTER CALIBRATION" in provider.tasks[0]
    assert "SYNTHETIC COVER LETTER CALIBRATION" not in provider.tasks[1]
    assert "Do not preview" in provider.tasks[0]
    assert "technical story that belongs in Paragraph 2" in provider.tasks[0]
    assert "Do not repeat" in provider.tasks[0]
    assert "the headline claim, metric" in provider.tasks[0]


def test_generated_resume_and_cover_use_source_supported_technology_casing() -> None:
    class Provider:
        available = True
        model_name = "test"

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            if response_model.__name__ == "GeneratedTailoring":
                return response_model.model_validate({
                    "profile": "", "profile_evidence_ids": [],
                    "sections": [{"type": "projects", "title": "Projects", "items": [{
                        "source_item_id": "section:0:item:0",
                        "bullets": [{"text": "Built a pytorch pipeline.",
                                     "evidence_ids": ["section:0:item:0:bullet:0"]}],
                    }]}], "skills": {}, "evidence_gaps": [], "strategy": {},
                })
            paragraphs = _valid_cover_paragraphs()
            paragraphs[0] = paragraphs[0].replace("Opening", "pytorch", 1)
            return response_model.model_validate({
                "salutation": "Dear Team,", "paragraphs": paragraphs,
                "closing": "Sincerely", "evidence_ids": ["section:0:item:0:bullet:0"],
            })

    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [{"type": "projects", "title": "Projects", "items": [
              {"title": "Pipeline", "bullets": ["Built a PyTorch pipeline."]},
          ]}]}
    provider = Provider()
    resume = asyncio.run(tailor_resume(cv, {}, provider))
    cover = asyncio.run(draft_cover(resume, "Example Co", "professional", provider))

    assert resume["sections"][0]["items"][0]["bullets"] == ["Built a PyTorch pipeline."]
    assert cover["paragraphs"][0].startswith("PyTorch ")


def test_cover_letter_rejects_blacklisted_term_missing_from_cited_evidence() -> None:
    class OfflineProvider:
        available = False
        model_name = "offline"

    class HallucinatingProvider:
        available = True
        model_name = "test"

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            paragraphs = _valid_cover_paragraphs()
            paragraphs[1] += " Ray workers."
            return response_model.model_validate({
                "salutation": "Dear Team,", "paragraphs": paragraphs,
                "closing": "Regards", "evidence_ids": ["skill:Languages:0"],
                "evidence_gaps": [],
            })

    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [], "skills": {"Languages": ["Python"]}}
    tailored = asyncio.run(tailor_resume(cv, {}, OfflineProvider()))

    with pytest.raises(ValueError, match="absent from cited evidence"):
        asyncio.run(draft_cover(
            tailored, "Example Co", "professional", HallucinatingProvider()
        ))


@pytest.mark.parametrize("repair", [True, False])
@pytest.mark.parametrize("role, source_tool, jd_tool", [
    ("customer_service", "Zendesk", "Salesforce"),
    ("finance_operations", "Excel", "SAP"),
])
def test_cover_letter_retries_jd_only_tool_without_weakening_citations(
    repair: bool, role: str, source_tool: str, jd_tool: str,
) -> None:
    class OfflineProvider:
        available = False
        model_name = "offline"

    class ToolProvider:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.tasks: list[str] = []

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.tasks.append(task)
            paragraphs = _valid_cover_paragraphs()
            paragraphs[1] += (
                f" {jd_tool}." if len(self.tasks) == 1 or not repair else f" {source_tool}."
            )
            return response_model.model_validate({
                "salutation": "Dear Team,", "paragraphs": paragraphs,
                "closing": "Sincerely", "evidence_ids": ["skill:Tools:0"],
            })

    cv = {
        "name": "Candidate", "contact": {"email": "test@example.com"},
        "sections": [], "skills": {"Tools": [source_tool]},
    }
    tailored = asyncio.run(tailor_resume(cv, {}, OfflineProvider()))
    provider = ToolProvider()

    if repair:
        cover = asyncio.run(draft_cover(
            tailored, "Example Co", "professional", provider,
            jd_analysis={"role_type": role, "nice_to_haves": [jd_tool]},
        ))
        assert source_tool in cover["paragraphs"][1]
        assert jd_tool not in " ".join(cover["paragraphs"])
        assert cover["evidence_ids"] == ["skill:Tools:0"]
    else:
        with pytest.raises(ValueError, match="absent from cited evidence"):
            asyncio.run(draft_cover(tailored, "Example Co", "professional", provider))
    assert len(provider.tasks) == 2
    assert jd_tool.casefold() in provider.tasks[1].casefold()
    assert "Do not claim tools merely because the JD requests them" in provider.tasks[1]


def test_cover_letter_tone_retries_with_feedback_and_lower_temperature() -> None:
    class OfflineProvider:
        available = False
        model_name = "offline"

    class Capture:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.calls: list[tuple[str, float]] = []

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.calls.append((task, temperature))
            paragraphs = _valid_cover_paragraphs()
            if len(self.calls) == 1:
                paragraphs[0] = "Passionate " + paragraphs[0]
            return response_model.model_validate({
                "salutation": "Dear Team,", "paragraphs": paragraphs,
                "closing": "Sincerely", "evidence_ids": ["skill:Languages:0"],
            })

    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [], "skills": {"Languages": ["Python"]}}
    tailored = asyncio.run(tailor_resume(cv, {}, OfflineProvider()))
    provider = Capture()
    cover = asyncio.run(draft_cover(tailored, "Example Co", "professional", provider))

    assert len(provider.calls) == 2
    assert [temperature for _, temperature in provider.calls] == [0.45, 0.25]
    assert "excessive_buzzwords: passionate" in provider.calls[1][0]
    assert "Passionate" not in cover["paragraphs"][0]


def test_cover_letter_tone_blocks_after_failed_rewrite() -> None:
    class OfflineProvider:
        available = False
        model_name = "offline"

    class AlwaysBuzzword:
        available = True
        model_name = "test"

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            paragraphs = _valid_cover_paragraphs()
            paragraphs[0] = "Passionate " + paragraphs[0]
            return response_model.model_validate({
                "salutation": "Dear Team,", "paragraphs": paragraphs,
                "closing": "Sincerely", "evidence_ids": ["skill:Languages:0"],
            })

    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [], "skills": {"Languages": ["Python"]}}
    tailored = asyncio.run(tailor_resume(cv, {}, OfflineProvider()))
    with pytest.raises(ValueError, match="critic failed: excessive_buzzwords: passionate"):
        asyncio.run(draft_cover(tailored, "Example Co", "professional", AlwaysBuzzword()))


def test_cover_letter_cross_paragraph_repetition_requests_rewrite() -> None:
    class OfflineProvider:
        available = False
        model_name = "offline"

    class RepeatingProvider:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.tasks: list[str] = []

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.tasks.append(task)
            paragraphs = _valid_cover_paragraphs()
            if len(self.tasks) == 1:
                paragraphs[1] = "Opening Opening Opening Opening Opening Opening. " + paragraphs[1]
            return response_model.model_validate({
                "salutation": "Dear Team,", "paragraphs": paragraphs,
                "closing": "Sincerely", "evidence_ids": ["skill:Languages:0"],
            })

    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [], "skills": {"Languages": ["Python"]}}
    tailored = asyncio.run(tailor_resume(cv, {}, OfflineProvider()))
    provider = RepeatingProvider()
    cover = asyncio.run(draft_cover(tailored, "Example Co", "professional", provider))
    assert len(provider.tasks) == 2
    assert "cross_paragraph_repetition:" in provider.tasks[1]
    assert "Do not just synonym-swap the repeated phrase" in provider.tasks[1]
    assert cover["paragraphs"] == _valid_cover_paragraphs()


@pytest.mark.parametrize("repair", [True, False])
def test_cover_letter_retries_unsupported_duration_with_strict_final_gate(repair: bool) -> None:
    class OfflineProvider:
        available = False
        model_name = "offline"

    class DurationProvider:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.tasks: list[str] = []

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.tasks.append(task)
            paragraphs = _valid_cover_paragraphs()
            if len(self.tasks) == 1 or not repair:
                paragraphs[0] = "2 years " + paragraphs[0]
            return response_model.model_validate({
                "salutation": "Dear Team,", "paragraphs": paragraphs,
                "closing": "Sincerely", "evidence_ids": ["skill:Tools:0"],
            })

    cv = {
        "name": "Candidate", "contact": {"email": "test@example.com"},
        "profile": "Finance analyst with documented reconciliation.",
        "sections": [], "skills": {"Tools": ["Excel"]},
    }
    tailored = asyncio.run(tailor_resume(cv, {}, OfflineProvider()))
    provider = DurationProvider()
    if repair:
        cover = asyncio.run(draft_cover(tailored, "Example Co", "professional", provider))
        assert cover["paragraphs"] == _valid_cover_paragraphs()
        assert cover["evidence_ids"] == ["skill:Tools:0"]
    else:
        with pytest.raises(ValueError, match="unsupported metrics.*2"):
            asyncio.run(draft_cover(tailored, "Example Co", "professional", provider))
    assert len(provider.tasks) == 2
    assert "Remove unsupported numeric claims" in provider.tasks[1]


@pytest.mark.parametrize("mixed_verified_metric", [False, True])
def test_cover_letter_bounded_numeric_sentence_removal_preserves_source_facts(
    mixed_verified_metric: bool,
) -> None:
    class OfflineProvider:
        available = False
        model_name = "offline"

    class StubbornProvider:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.calls = 0

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.calls += 1
            paragraphs = _valid_cover_paragraphs()
            paragraphs[1] += (
                " Handled 120 invoices with a 64% gain."
                if mixed_verified_metric else " Delivered an invented 64% gain."
            )
            return response_model.model_validate({
                "salutation": "Dear Team,", "paragraphs": paragraphs,
                "closing": "Sincerely", "evidence_ids": ["profile"],
            })

    cv = {
        "name": "Candidate", "contact": {"email": "test@example.com"},
        "profile": "Processed 120 invoices in Excel.", "sections": [], "skills": {},
    }
    tailored = asyncio.run(tailor_resume(cv, {}, OfflineProvider()))
    provider = StubbornProvider()

    if mixed_verified_metric:
        with pytest.raises(ValueError, match="unsupported metrics.*64"):
            asyncio.run(draft_cover(tailored, "Example Co", "professional", provider))
    else:
        cover = asyncio.run(draft_cover(tailored, "Example Co", "professional", provider))
        assert cover["paragraphs"] == _valid_cover_paragraphs()
        assert cover["evidence_ids"] == ["profile"]
        assert cover["evidence_gaps"] == [
            "Removed unsupported numeric sentence from paragraph 2"
        ]
    assert provider.calls == 2


def test_cover_prompt_numeric_claims_are_grounded_per_evidence_id() -> None:
    class OfflineProvider:
        available = False
        model_name = "offline"

    class CaptureProvider:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.task = ""
            self.payload = {}

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.task = task
            self.payload = payload
            return response_model.model_validate({
                "salutation": "Dear Team,", "paragraphs": _valid_cover_paragraphs(),
                "closing": "Sincerely", "evidence_ids": ["section:0:item:0:bullet:0"],
            })

    cv = {
        "name": "Candidate", "contact": {"email": "test@example.com"},
        "sections": [{"type": "experience", "title": "Finance Experience", "items": [{
            "title": "Analyst", "organization": "Example", "dates": "2024--2026",
            "bullets": [
                "Reconciled 120 supplier invoices in Excel.",
                "Reduced exceptions by 8% with documented checks.",
                "Prepared audit-ready month-end reports.",
            ],
        }]}], "skills": {"Tools": ["Excel"]},
    }
    tailored = asyncio.run(tailor_resume(cv, {}, OfflineProvider()))
    provider = CaptureProvider()

    asyncio.run(draft_cover(
        tailored, "Example Co", "professional", provider,
        jd_analysis={"role_type": "finance_operations", "nice_to_haves": ["SAP"]},
    ))

    numeric = provider.payload["VERIFIED_NUMERIC_CLAIMS_BY_EVIDENCE_ID"]
    assert "120" in numeric["section:0:item:0:bullet:0"]
    assert "8%" in numeric["section:0:item:0:bullet:1"]
    assert "section:0:item:0:bullet:2" not in numeric
    assert "2" not in {value for values in numeric.values() for value in values}
    assert "64" not in {value for values in numeric.values() for value in values}
    assert "do not calculate years" in provider.task


def test_dynamic_resume_exemplars_match_role_and_pydantic_dto() -> None:
    class Capture:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.tasks = []

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.tasks.append(task)
            return response_model.model_validate({
                "profile": "", "profile_evidence_ids": [], "sections": [{
                    "type": "projects", "title": "Projects", "items": [{
                        "source_item_id": "section:0:item:0",
                        "bullets": [{"text": "Built a Python API.",
                                     "evidence_ids": ["section:0:item:0:bullet:0"]}],
                    }],
                }], "skills": {}, "evidence_gaps": [],
                "strategy": {"item_scores": {"section:0:item:0": 999}},
            })

    validate_exemplars()
    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [{"type": "projects", "title": "Projects", "items": [
              {"title": "API", "bullets": ["Built a Python API."]}
          ]}]}
    provider = Capture()
    role_ids = {
        "ai_research": "example:ai:0",
        "quant_fintech": "example:quant:0",
        "systems_infra": "example:systems:0",
        "data_engineering": "example:data:0",
        "general_software": "example:software:0",
    }
    for role in role_ids:
        result = asyncio.run(tailor_resume(cv, {"role_type": role}, provider))
        assert result["strategy"]["item_scores"] == {"section:0:item:0": 0}

    for task, selected in zip(provider.tasks, role_ids.values()):
        assert "SYNTHETIC CALIBRATION EXAMPLES ONLY" in task
        assert "example:polish:0" in task
        assert selected in task
        assert all(other not in task for other in role_ids.values() if other != selected)
    assert "SYNTHETIC COVER LETTER CALIBRATION" in cover_exemplar()
    assert "example:software:0" in resume_exemplars("unknown")


def test_resume_exemplars_use_modern_role_prototypes() -> None:
    task = resume_exemplars("quant_fintech")
    assert "C++" in task
    assert "sub-10ms" in task
    assert "order-book" in task.lower()


def test_contrastive_examples_show_verified_information_loss() -> None:
    examples = {
        "ai_research": ("5%", "PPO"),
        "quant_fintech": ("22%", "Ray-powered"),
        "systems_infra": ("20%", "containerized"),
    }

    for role, (omission, hallucination) in examples.items():
        task = resume_exemplars(role)
        assert omission in task
        assert hallucination in task
        assert task.count("GOOD DTO:") == 2

    assert "sub-10ms" in resume_exemplars("quant_fintech")
    assert "35%" in resume_exemplars("systems_infra")


def test_chinese_resume_generation_keeps_evidence_and_metrics() -> None:
    class ChineseProvider:
        available = True
        model_name = "test"

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            assert "natural Simplified Chinese" in task
            assert payload["JD_ANALYSIS"]["resume_language"] == "zh_CN"
            return response_model.model_validate({
                "profile": "", "profile_evidence_ids": [],
                "sections": [{"type": "projects", "title": "Projects", "items": [{
                    "source_item_id": "section:0:item:0",
                    "bullets": [{"text": "使用 Python 构建数据流水线，将错误率降低 5.2%",
                                 "evidence_ids": ["section:0:item:0:bullet:0"]}],
                }]}],
                "skills": {"Claims": ["Unverified distributed training"]},
                "evidence_gaps": [], "strategy": {},
            })

    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [{"type": "projects", "title": "Projects", "items": [
              {"title": "Pipeline", "bullets": ["Built a Python pipeline and reduced error by 5.2%."]}
          ]}], "skills": {"Languages": ["Python"]}}
    result = asyncio.run(tailor_resume(cv, {"resume_language": "zh_CN"}, ChineseProvider()))
    item = result["sections"][0]["items"][0]

    assert item["bullets"] == ["使用 Python 构建数据流水线，将错误率降低 5.2%。"]
    assert item["evidence_ids"] == ["section:0:item:0:bullet:0"]
    assert result["skills"] == {"Languages": ["Python"]}


@pytest.mark.parametrize("repair", [True, False])
def test_chinese_resume_retries_untranslated_bullet(repair: bool) -> None:
    class ChineseProvider:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.tasks: list[str] = []

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.tasks.append(task)
            bullet = (
                "使用 Python 构建流水线。" if repair and len(self.tasks) == 2
                else "Built a Python pipeline."
            )
            return response_model.model_validate({
                "profile": "", "profile_evidence_ids": [],
                "sections": [{"type": "projects", "title": "Projects", "items": [{
                    "source_item_id": "section:0:item:0",
                    "bullets": [{"text": bullet,
                                 "evidence_ids": ["section:0:item:0:bullet:0"]}],
                }]}], "skills": {}, "evidence_gaps": [], "strategy": {},
            })

    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [{"type": "projects", "title": "Projects", "items": [
              {"title": "Pipeline", "bullets": ["Built a Python pipeline."]},
          ]}]}
    provider = ChineseProvider()
    if repair:
        result = asyncio.run(tailor_resume(cv, {"resume_language": "zh_CN"}, provider))
        assert result["sections"][0]["items"][0]["bullets"] == ["使用 Python 构建流水线。"]
    else:
        with pytest.raises(ValueError, match="Chinese resume requires Chinese text"):
            asyncio.run(tailor_resume(cv, {"resume_language": "zh_CN"}, provider))
    assert len(provider.tasks) == 2
    assert "section:0:item:0" in provider.tasks[1]


def test_chinese_resume_rejects_unverified_tool() -> None:
    class HallucinatingProvider:
        available = True
        model_name = "test"

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            return response_model.model_validate({
                "profile": "", "profile_evidence_ids": [],
                "sections": [{"type": "projects", "title": "Projects", "items": [{
                    "source_item_id": "section:0:item:0",
                    "bullets": [{"text": "使用 Ray 构建 Python 流水线。",
                                 "evidence_ids": ["section:0:item:0:bullet:0"]}],
                }]}], "skills": {}, "evidence_gaps": [], "strategy": {},
            })

    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [{"type": "projects", "title": "Projects", "items": [
              {"title": "Pipeline", "bullets": ["Built a Python pipeline."]}
          ]}]}

    with pytest.raises(ValueError, match="unverified tools"):
        asyncio.run(tailor_resume(cv, {"resume_language": "zh_CN"}, HallucinatingProvider()))


@pytest.mark.parametrize("tool", ["Kubernetes", "Ray"])
def test_english_resume_rejects_unverified_technology(tool: str) -> None:
    class HallucinatingProvider:
        available = True
        model_name = "test"

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            return response_model.model_validate({
                "profile": "", "profile_evidence_ids": [],
                "sections": [{"type": "projects", "title": "Projects", "items": [{
                    "source_item_id": "section:0:item:0",
                    "bullets": [{
                        "text": f"Built a {tool} service with Python.",
                        "evidence_ids": ["section:0:item:0:bullet:0"],
                    }],
                }]}], "skills": {}, "evidence_gaps": [], "strategy": {},
            })

    cv = {
        "name": "Candidate", "contact": {"email": "test@example.com"},
        "sections": [{"type": "projects", "title": "Projects", "items": [
            {"title": "Pipeline", "bullets": ["Built a Python pipeline."]},
        ]}],
    }

    with pytest.raises(ValueError, match="unverified tools/technologies"):
        asyncio.run(tailor_resume(cv, {"resume_language": "en"}, HallucinatingProvider()))


def test_resume_retries_technology_claim_without_item_evidence() -> None:
    class RepairingProvider:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.tasks: list[str] = []
            self.temperatures: list[float] = []

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.tasks.append(task)
            self.temperatures.append(temperature)
            bullet = (
                "Built a Python pipeline."
                if len(self.tasks) == 1 else "Built a documented pipeline."
            )
            return response_model.model_validate({
                "profile": "", "profile_evidence_ids": [],
                "sections": [{"type": "projects", "title": "Projects", "items": [{
                    "source_item_id": "section:0:item:0",
                    "bullets": [{"text": bullet,
                                 "evidence_ids": ["section:0:item:0:bullet:0"]}],
                }]}], "skills": {"Languages": ["Python"]},
                "evidence_gaps": [], "strategy": {},
            })

    cv = {"name": "Candidate", "contact": {"email": "test@example.com"},
          "sections": [{"type": "projects", "title": "Projects", "items": [
              {"title": "Pipeline", "bullets": ["Built a documented pipeline."]},
          ]}], "skills": {"Languages": ["Python"]}}
    provider = RepairingProvider()
    result = asyncio.run(tailor_resume(cv, {"resume_language": "en"}, provider))

    assert provider.temperatures == [0.45, 0.25]
    assert "section:0:item:0" in provider.tasks[1]
    assert "python" in provider.tasks[1].casefold()
    assert result["sections"][0]["items"][0]["bullets"] == ["Built a documented pipeline."]


@pytest.mark.parametrize("repair", [True, False])
def test_resume_retries_unsupported_experience_duration_and_restores_source_profile(
    repair: bool,
) -> None:
    class DurationProvider:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.tasks: list[str] = []

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.tasks.append(task)
            profile = (
                "Finance analyst with documented reconciliation."
                if repair and len(self.tasks) == 2 else
                "Finance analyst with 2 years of reconciliation experience."
            )
            return response_model.model_validate({
                "profile": profile, "profile_evidence_ids": ["profile"],
                "sections": [{"type": "experience", "title": "Experience", "items": [{
                    "source_item_id": "section:0:item:0",
                    "bullets": [{"text": "Reconciled 120 invoices in Excel.",
                                 "evidence_ids": ["section:0:item:0:bullet:0"]}],
                }]}], "skills": {"Tools": ["Excel"]}, "evidence_gaps": [], "strategy": {},
            })

    cv = {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "profile": "Finance analyst with documented reconciliation.",
        "sections": [{"type": "experience", "title": "Experience", "items": [{
            "title": "Finance Analyst", "organization": "Example", "dates": "2024--2026",
            "bullets": ["Reconciled 120 invoices in Excel."],
        }]}], "skills": {"Tools": ["Excel"]},
    }
    provider = DurationProvider()
    if repair:
        result = asyncio.run(tailor_resume(cv, {"role_type": "finance_operations"}, provider))
        assert result["profile"] == "Finance analyst with documented reconciliation."
        assert "120" in result["sections"][0]["items"][0]["bullets"][0]
        assert not any("Restored source profile" in gap for gap in result["evidence_gaps"])
    else:
        result = asyncio.run(tailor_resume(cv, {"role_type": "finance_operations"}, provider))
        assert result["profile"] == cv["profile"]
        assert "Restored source profile after unsupported numeric claim" in result["evidence_gaps"]
        assert "120" in result["sections"][0]["items"][0]["bullets"][0]
    assert len(provider.tasks) == 2
    assert "Unsupported numeric claims" in provider.tasks[1]
    assert "derived years of experience" in provider.tasks[1]


def test_resume_restores_only_bullet_with_persistent_unsupported_metric() -> None:
    class DurationProvider:
        available = True
        model_name = "test"

        def __init__(self) -> None:
            self.calls = 0

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            self.calls += 1
            return response_model.model_validate({
                "profile": "Finance analyst with documented reconciliation.",
                "profile_evidence_ids": ["profile"],
                "sections": [{"type": "experience", "title": "Experience", "items": [{
                    "source_item_id": "section:0:item:0",
                    "bullets": [{"text": "Reconciled 120 invoices in Excel over 2 years.",
                                 "evidence_ids": ["section:0:item:0:bullet:0"]}],
                }]}], "skills": {"Tools": ["Excel"]}, "evidence_gaps": [], "strategy": {},
            })

    cv = {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "profile": "Finance analyst with documented reconciliation.",
        "sections": [{"type": "experience", "title": "Experience", "items": [{
            "title": "Finance Analyst", "organization": "Example", "dates": "2024--2026",
            "bullets": ["Reconciled 120 invoices in Excel."],
        }]}], "skills": {"Tools": ["Excel"]},
    }
    provider = DurationProvider()

    result = asyncio.run(tailor_resume(cv, {"role_type": "finance_operations"}, provider))

    assert provider.calls == 2
    assert result["sections"][0]["items"][0]["bullets"] == cv["sections"][0]["items"][0]["bullets"]
    assert result["profile"] == cv["profile"]
    assert result["evidence_gaps"] == [
        "Restored source bullet after unsupported numeric claim: section:0:item:0:0"
    ]


def test_resume_drops_unsupported_skill_labels_without_aborting_generation() -> None:
    class SkillLabelProvider:
        available = True
        model_name = "test"

        async def complete_json(self, task, payload, response_model, temperature=0.2):
            return response_model.model_validate({
                "profile": "Python engineer.",
                "profile_evidence_ids": ["profile"],
                "sections": [],
                "skills": {"Languages": ["Python"], "Claims": ["Distributed Training"]},
                "evidence_gaps": [],
                "strategy": {},
            })

    cv = {
        "name": "Candidate",
        "contact": {"email": "candidate@example.com"},
        "profile": "Python engineer.",
        "sections": [],
        "skills": {"Languages": ["Python"]},
    }

    result = asyncio.run(tailor_resume(cv, {}, SkillLabelProvider()))

    assert result["skills"] == {"Languages": ["Python"]}
    assert result["evidence_gaps"] == ["Removed unsupported skill label: Distributed Training"]
