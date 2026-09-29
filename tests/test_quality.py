import pytest

from career_resume_skill.quality import (
    _text_metrics,
    check_linear_text_stream,
    document_quality_report,
    lint_output_integrity,
    lint_payload_bullets,
)


def test_quality_metrics_distinguish_hyphen_and_duplicate_lines() -> None:
    metrics = _text_metrics("alpha\nalpha\nand- -preference\n\uf0b7")

    assert metrics["duplicate_nonempty_lines"] == 1
    assert metrics["hyphen_space_hyphen"] == 1
    assert metrics["private_bullet"] == 1
    assert metrics["trailing_dash_lines"] == 0


def test_quality_metrics_do_not_flag_normal_hyphenated_words() -> None:
    metrics = _text_metrics("out-of-domain\n16-bit\nequal-strength")

    assert metrics["hyphen_space_hyphen"] == 0
    assert metrics["soft_hyphen"] == 0


def test_quality_metrics_detect_trailing_dash_lines() -> None:
    metrics = _text_metrics("Impact statement.\u2011\u2011\u2011")

    assert metrics["trailing_dash_lines"] == 1


def test_integrity_linter_blocks_missing_metrics_bad_punctuation_glyphs_and_pages() -> None:
    report = lint_output_integrity(
        "Improved throughput by 12.5% with sub-10ms latency.",
        "Improved throughput—\uf0b7",
        2,
        bullet_texts=["Improved throughput—"],
    )

    assert report["passed"] is False
    assert report["checks"]["page_budget"]["passed"] is False
    assert report["checks"]["key_metric_invariance"]["missing"] == ["12.5%", "sub-10ms"]
    assert report["checks"]["punctuation"]["passed"] is False
    assert report["checks"]["glyph_hygiene"]["passed"] is False


def test_integrity_linter_accepts_preserved_metrics_and_clean_single_page_output() -> None:
    report = lint_output_integrity(
        "Improved throughput by 12.5% with sub-10ms latency.",
        "Improved throughput by 12.5% with sub-10ms latency.",
        1,
        bullet_texts=["Improved throughput by 12.5% with sub-10ms latency."],
    )

    assert report["passed"] is True


def test_integrity_linter_rejects_unauthorized_and_blacklisted_technologies() -> None:
    report = lint_output_integrity(
        "Built Python services.",
        "Built Python services with Kubernetes and Ray.",
        1,
    )

    assert report["passed"] is False
    assert report["checks"]["technology_provenance"]["unauthorized"] == ["kubernetes"]
    assert report["checks"]["hallucination_blacklist"]["unauthorized"] == ["ray"]


def test_integrity_linter_rejects_pdf_trailing_dash_artifacts() -> None:
    report = lint_output_integrity(
        "Built a Python service.",
        "Built a Python service.-----\n",
        1,
        bullet_texts=["Built a Python service.-----"],
    )

    assert report["passed"] is False
    assert report["checks"]["punctuation"]["passed"] is False
    assert report["checks"]["punctuation"]["trailing_dash_bullets"] == [
        "Built a Python service.-----"
    ]


def test_integrity_linter_ignores_pdf_word_break_hyphens() -> None:
    report = lint_output_integrity(
        "Built a Python service.",
        "Built an eval-\nuation pipeline.\nMeasured results.",
        1,
    )

    assert report["checks"]["punctuation"]["passed"] is True


def test_pdf_metrics_ignore_repeated_dash_extraction_artifacts_but_keep_word_hyphens() -> None:
    metrics = _text_metrics(
        "Completed deployment.-----\nfull-\nBuilt out-of-domain.",
        normalize_pdf_artifacts=True,
    )

    assert metrics["trailing_dash_lines"] == 0


def test_pdf_text_extraction_strips_repeated_dash_artifacts_after_punctuation(tmp_path) -> None:
    pdf = tmp_path / "extracted.pdf"
    pdf.write_bytes(b"placeholder")

    from career_resume_skill import quality

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            quality,
            "PdfReader",
            lambda _: type("Reader", (), {
                "pages": [type("Page", (), {"extract_text": lambda self: "Sentence.-----\n16-bit"})()]
            })(),
        )
        _, text = quality.extract_pdf_text(pdf)
    finally:
        monkeypatch.undo()

    assert text == "Sentence.\n16-bit"


def test_payload_linter_checks_technology_and_blacklist_provenance() -> None:
    report = lint_payload_bullets(
        "Built Python services.",
        ["Built Python services with Kubernetes and Ray."],
    )

    assert report["passed"] is False
    assert report["unauthorized_technologies"] == ["kubernetes"]
    assert report["blacklisted_terms"] == ["ray"]


def test_integrity_linters_accept_source_backed_technology_aliases() -> None:
    source = "Built a multi‑agent AI assistant with LLM‑driven reasoning and supervised finetuning."
    output = "Built Multi-Agent Systems with LLM Reasoning and supervised fine-tuning."

    integrity = lint_output_integrity(source, output, 1)
    payload = lint_payload_bullets(source, [output + "."])

    assert integrity["checks"]["technology_provenance"]["passed"] is True
    assert payload["unauthorized_technologies"] == []


def test_integrity_linter_preserves_superscripts_and_sub_latency() -> None:
    report = lint_output_integrity("Handled 10⁶ events in sub-10ms.",
                                   "Handled 10⁷ events in 10ms.", 1)

    assert report["checks"]["key_metric_invariance"]["missing"] == ["10⁶", "sub-10ms"]


def test_integrity_linter_detects_scientific_exponent_change() -> None:
    report = lint_output_integrity("Measured 1e-6 error.", "Measured 1e-5 error.", 1)

    assert report["checks"]["key_metric_invariance"]["missing"] == ["1e-6"]


def test_integrity_linter_normalizes_nonbreaking_metric_hyphen() -> None:
    report = lint_output_integrity(
        "Measured sub‑10ms latency.", "Measured sub-10ms latency.", 1
    )

    assert report["checks"]["key_metric_invariance"]["passed"] is True


def test_integrity_linter_accepts_pdf_extraction_space_before_sub_hyphen() -> None:
    report = lint_output_integrity(
        "Measured sub‑10ms latency.", "Measured sub -10ms latency.", 1
    )

    assert report["checks"]["key_metric_invariance"]["passed"] is True


def test_preflight_blocks_bad_payload_before_docx_injection() -> None:
    report = lint_payload_bullets(
        "Improved latency by 12.5%.", ["Improved latency..", "Bad  spacing.\uf0b7"]
    )

    assert report["passed"] is False
    assert report["missing_metrics"] == ["12.5%"]
    assert report["invalid_bullet_indices"] == [0, 1]
    assert report["private_use_codepoints"] == ["U+F0B7"]


def test_chinese_preflight_requires_fullwidth_period() -> None:
    report = lint_payload_bullets(
        "优化了数据管道。",
        ["优化了数据管道。", "优化了数据管道."],
        language="zh_CN",
    )

    assert report["passed"] is False
    assert report["invalid_bullet_indices"] == [1]


def test_document_quality_report_distinguishes_reduction_from_overflow(monkeypatch) -> None:
    from career_resume_skill import quality

    monkeypatch.setattr(quality, "_docx_text", lambda path: "")
    monkeypatch.setattr(quality, "extract_pdf_text", lambda path: (2, "source") if path == "source.pdf" else (1, "output"))
    monkeypatch.setattr(quality, "pdf_visual_metrics", lambda path: {})
    monkeypatch.setattr(quality, "_text_metrics", lambda text, **kwargs: {
        "private_bullet": 0, "hyphen_space_hyphen": 0, "duplicate_nonempty_lines": 0,
    })
    monkeypatch.setattr(quality, "import_docx_as_master_cv", lambda path: {
        "master_cv": {"sections": []},
    })

    report = document_quality_report(
        "source.docx", "output.docx", "source.pdf", "output.pdf", 0
    )

    assert report["diagnosis"]["page_count_exceeded"] is False
    assert report["diagnosis"]["page_reduced"] is True
    assert report["diagnosis"]["page_count_changed"] is True


def test_ats_text_stream_flags_order_and_field_separation() -> None:
    items = [
        {"title": "Backend Engineer", "organization": "First Lab", "dates": "01.2024"},
        {"title": "ML Engineer", "organization": "Second Lab", "dates": "02.2025"},
    ]
    stream = "ML Engineer\nSecond Lab 02.2025\nBackend Engineer\nOther line\nOther line\nFirst Lab 01.2024"

    result = check_linear_text_stream(items, stream, ["Shipped reliable APIs."])
    codes = {flag["code"] for flag in result["ats_readability_flags"]}

    assert {"item_out_of_order", "organization_not_near_title", "dates_not_near_title",
            "bullet_not_contiguous"} <= codes


def test_ats_text_stream_accepts_ordered_repeated_titles() -> None:
    items = [{"title": "Engineer"}, {"title": "Engineer"}]
    result = check_linear_text_stream(
        items, "Engineer\nBuilt reliable APIs.\nEngineer\nImproved throughput.",
        ["Built reliable APIs.", "Improved throughput."],
    )

    assert result["ats_readability_flags"] == []
