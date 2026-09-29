import asyncio

from career_resume_skill import typography
from career_resume_skill.refinement import _deviation, refine_one_bullet
from career_resume_skill.typography import estimate_string_width, evaluate_bullet_geometry


class _PatchProvider:
    available = True
    model_name = "test"

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = []
        self.tasks = []

    async def complete_json(self, task, payload, response_model, temperature=0.2):
        self.calls.append(payload)
        self.tasks.append(task)
        return response_model(text=self.text)


def _inputs():
    long_bullet = "Improved Python pipeline latency by 5.2% using verified tools and test results. " * 8
    short_bullet = "Shipped a reliable API."
    master = {
        "name": "Candidate",
        "contact": {"email": "candidate@example.com"},
        "sections": [{"type": "projects", "title": "Projects", "items": [
            {"title": "Pipeline", "bullets": [long_bullet, short_bullet]},
        ]}],
    }
    candidate = {"sections": [{"items": [{
        "source_item_id": "section:0:item:0",
        "bullets": [long_bullet, short_bullet],
    }]}]}
    item_map = {"section:0:item:0": {"bullet_paragraph_ids": ["p:0:body", "p:1:body"]}}
    layout = {"paragraphs": [
        {"paragraph_id": paragraph_id, "font_name": "Arial", "font_size_pt": 10,
         "available_width_pt": 110}
        for paragraph_id in ("p:0:body", "p:1:body")
    ]}
    return master, candidate, item_map, layout


def test_refinement_patches_only_the_worst_bullet() -> None:
    master, candidate, item_map, layout = _inputs()
    original_other = candidate["sections"][0]["items"][0]["bullets"][1]
    provider = _PatchProvider("Improved Python latency by 5.2%.")

    trace = asyncio.run(refine_one_bullet(candidate, master, item_map, layout, provider))

    assert trace["outcome"] == "patch_accepted"
    assert trace["worst_bullet"]["bullet_index"] == 0
    assert len(provider.calls) == 1
    assert "sections" not in provider.calls[0]
    assert candidate["sections"][0]["items"][0]["bullets"] == [
        "Improved Python latency by 5.2%.", original_other,
    ]


def test_refinement_rejects_patch_that_drops_verified_metric() -> None:
    master, candidate, item_map, layout = _inputs()
    original = list(candidate["sections"][0]["items"][0]["bullets"])
    provider = _PatchProvider("Improved Python latency.")

    trace = asyncio.run(refine_one_bullet(candidate, master, item_map, layout, provider))

    assert trace["outcome"].startswith("patch_rejected")
    assert candidate["sections"][0]["items"][0]["bullets"] == original


def test_page_overflow_shortens_only_one_bullet() -> None:
    master, candidate, item_map, layout = _inputs()
    other = candidate["sections"][0]["items"][0]["bullets"][1]
    provider = _PatchProvider("Improved Python latency by 5.2% using verified tools.")

    trace = asyncio.run(refine_one_bullet(
        candidate, master, item_map, layout, provider, page_overflow=True
    ))

    assert trace["outcome"] == "patch_accepted"
    assert len(provider.calls) == 1
    assert candidate["sections"][0]["items"][0]["bullets"][1] == other


def test_refinement_rejects_unverified_technology() -> None:
    master, candidate, item_map, layout = _inputs()
    original = list(candidate["sections"][0]["items"][0]["bullets"])
    provider = _PatchProvider("Improved Python latency by 5.2% on Ray.")

    trace = asyncio.run(refine_one_bullet(candidate, master, item_map, layout, provider))

    assert "unverified technologies" in trace["outcome"]
    assert candidate["sections"][0]["items"][0]["bullets"] == original


def test_orphan_word_geometry_detects_single_last_word() -> None:
    width = estimate_string_width("Built a pipeline", "Arial", 10) + 1
    geometry = evaluate_bullet_geometry("Built a pipeline deployment.", width, "Arial", 10)

    assert geometry["estimated_lines"] == 2
    assert geometry["last_line_words"] == 1
    assert geometry["orphan_words"] is True


def test_tier_three_one_line_bullet_is_within_geometry_budget() -> None:
    geometry = {
        "estimated_lines": 1,
        "last_line_ratio": 0.8,
        "orphan_words": False,
    }

    assert _deviation(geometry, target_lines=1) == 0


def test_missing_source_item_id_uses_fallback_budget_key() -> None:
    bullet = "A concise result."
    source_id = "section:0:item:0"
    candidate = {"sections": [{"items": [{"bullets": [bullet]}]}]}
    master = {
        "name": "Candidate", "contact": {"email": "candidate@example.com"},
        "sections": [{"type": "projects", "title": "Projects", "items": [{
            "title": "Project", "bullets": [bullet],
        }]}],
    }
    source_item_map = {source_id: {"bullet_paragraph_ids": ["p:0:body"]}}
    layout = {"paragraphs": [{
        "paragraph_id": "p:0:body", "font_name": "Arial", "font_size_pt": 10,
        "available_width_pt": 300,
    }]}

    trace = asyncio.run(refine_one_bullet(
        candidate, master, source_item_map, layout, _PatchProvider(bullet),
        audit_only=True, item_budgets={source_id: {"tier": "tier_3"}},
    ))

    assert trace["worst_bullet"]["source_item_id"] == source_id
    assert trace["worst_bullet"]["target_lines"] == 1


def test_chinese_overflow_refinement_uses_character_budget_and_fullwidth_stop() -> None:
    original = "使用 Python 构建高并发数据处理与分析流程，并优化批次运行的稳定性。"
    master = {
        "name": "候选人", "contact": {"email": "candidate@example.com"},
        "sections": [{"type": "projects", "title": "项目", "items": [{
            "source_item_id": "section:0:item:0", "title": "数据流程",
            "bullets": [original],
        }]}],
    }
    candidate = {"sections": [{"items": [{
        "source_item_id": "section:0:item:0", "bullets": [original],
    }]}]}
    item_map = {"section:0:item:0": {"bullet_paragraph_ids": ["p:0:body"]}}
    layout = {"paragraphs": [{
        "paragraph_id": "p:0:body", "font_name": "Arial", "font_size_pt": 10,
        "available_width_pt": 110,
    }]}
    provider = _PatchProvider("使用 Python 优化数据流程.")

    trace = asyncio.run(refine_one_bullet(
        candidate, master, item_map, layout, provider, page_overflow=True,
        item_budgets={"section:0:item:0": {
            "tier": "tier_2", "rewrite_intensity": "strategic_re_anchoring",
        }},
    ))

    assert "中文字符" in provider.tasks[0]
    assert trace["outcome"] == "patch_accepted"
    assert candidate["sections"][0]["items"][0]["bullets"] == ["使用 Python 优化数据流程。"]


def test_cjk_geometry_counts_character_units_and_flags_single_character_tail(monkeypatch) -> None:
    class FixedWidthFont:
        def getlength(self, text: str) -> int:
            return len(text)

    monkeypatch.setattr(typography, "_font", lambda *args, **kwargs: FixedWidthFont())

    geometry = evaluate_bullet_geometry("中文简历经历项", 2.25, "test", 10)

    assert geometry["estimated_lines"] == 3
    assert geometry["last_line_words"] == 1
    assert geometry["orphan_words"] is True


def test_mixed_cjk_latin_tail_counts_latin_word_as_one_unit(monkeypatch) -> None:
    class FixedWidthFont:
        def getlength(self, text: str) -> int:
            return len(text)

    monkeypatch.setattr(typography, "_font", lambda *args, **kwargs: FixedWidthFont())

    geometry = evaluate_bullet_geometry("中文 Python", 4.5, "test", 10)

    assert geometry["estimated_lines"] == 2
    assert geometry["last_line_words"] == 1
    assert geometry["orphan_words"] is True


def test_cjk_line_breaks_keep_closing_punctuation_with_previous_line(monkeypatch) -> None:
    class FixedWidthFont:
        def getlength(self, text: str) -> int:
            return len(text)

    monkeypatch.setattr(typography, "_font", lambda *args, **kwargs: FixedWidthFont())

    lines = typography._wrapped_line_details("中文，简历", 1.5, "test", 10)

    assert [width for width, _ in lines] == [2.25, 1.5]


def test_cjk_line_breaks_move_opening_punctuation_to_next_line(monkeypatch) -> None:
    class FixedWidthFont:
        def getlength(self, text: str) -> int:
            return len(text)

    monkeypatch.setattr(typography, "_font", lambda *args, **kwargs: FixedWidthFont())

    lines = typography._wrapped_line_details("中文（简历", 1.5, "test", 10)

    assert [width for width, _ in lines] == [1.5, 1.5, 0.75]


def test_pdf_overflow_prefers_lower_priority_item() -> None:
    master, candidate, item_map, layout = _inputs()
    ancillary = "Measured calibrated sensors with Python in repeatable tests. " * 2
    master["sections"][0]["items"].append({"title": "Sensor", "bullets": [ancillary]})
    candidate["sections"][0]["items"].append({
        "source_item_id": "section:0:item:1", "bullets": [ancillary],
    })
    item_map["section:0:item:1"] = {"bullet_paragraph_ids": ["p:2:body"]}
    layout["paragraphs"].append({
        "paragraph_id": "p:2:body", "font_name": "Arial", "font_size_pt": 10,
        "available_width_pt": 110,
    })
    provider = _PatchProvider("Measured calibrated sensors with Python in repeatable tests.")
    hero_original = candidate["sections"][0]["items"][0]["bullets"][0]

    trace = asyncio.run(refine_one_bullet(
        candidate, master, item_map, layout, provider, page_overflow=True,
        item_budgets={
            "section:0:item:0": {"tier": "tier_1", "rewrite_intensity": "full_lexical_projection"},
            "section:0:item:1": {"tier": "tier_3", "rewrite_intensity": "polish_only"},
        },
    ))

    assert trace["outcome"] == "patch_accepted"
    assert trace["worst_bullet"]["source_item_id"] == "section:0:item:1"
    assert candidate["sections"][0]["items"][0]["bullets"][0] == hero_original