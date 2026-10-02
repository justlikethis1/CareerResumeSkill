from lxml import etree as ET

from career_resume_skill.docx_sanitizer import W_NS, DocxTreeSanitizer, LexicalSanitizer
from career_resume_skill.harness.assertions import TypographyLinter


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def test_lexical_sanitizer_preserves_valid_hyphens_and_chinese_punctuation() -> None:
    assert LexicalSanitizer.clean_text("• Built an out-of-domain 16-bit model.-----") == (
        "Built an out-of-domain 16-bit model."
    )
    assert LexicalSanitizer.clean_text("使用 Python 完成评估。\u200b___") == "使用 Python 完成评估。"


def test_docx_tree_sanitizer_removes_body_tabs_but_preserves_style_alignment() -> None:
    document = ET.Element(_w("document"))
    body = ET.SubElement(document, _w("body"))
    paragraph = ET.SubElement(body, _w("p"))
    properties = ET.SubElement(paragraph, _w("pPr"))
    tabs = ET.SubElement(properties, _w("tabs"))
    tab_stop = ET.SubElement(tabs, _w("tab"))
    tab_stop.set(_w("leader"), "hyphen")
    run = ET.SubElement(paragraph, _w("r"))
    ET.SubElement(run, _w("tab"))

    styles = ET.Element(_w("styles"))
    style_properties = ET.SubElement(ET.SubElement(styles, _w("style")), _w("pPr"))
    style_tabs = ET.SubElement(style_properties, _w("tabs"))
    style_tab = ET.SubElement(style_tabs, _w("tab"))
    style_tab.set(_w("val"), "right")
    style_tab.set(_w("leader"), "hyphen")

    DocxTreeSanitizer.sanitize_document(document, styles)

    assert list(document.iter(_w("tab"))) == []
    assert style_tab.get(_w("val")) == "right"
    assert style_tab.get(_w("leader")) is None


def test_docx_tree_sanitizer_keeps_right_aligned_location_not_trailing_bullet_tab() -> None:
    document = ET.Element(_w("document"))
    body = ET.SubElement(document, _w("body"))
    for company, separator, location in (
        ("First Company", "               ", "Zhejiang, China"),
        ("Second Company", None, "Zhejiang, China"),
        ("Trailing body tab", None, None),
    ):
        paragraph = ET.SubElement(body, _w("p"))
        tabs = ET.SubElement(ET.SubElement(paragraph, _w("pPr")), _w("tabs"))
        tab = ET.SubElement(tabs, _w("tab"))
        tab.set(_w("val"), "right")
        tab.set(_w("pos"), "9000")
        ET.SubElement(ET.SubElement(paragraph, _w("r")), _w("t")).text = company
        run = ET.SubElement(paragraph, _w("r"))
        if separator:
            ET.SubElement(run, _w("t")).text = separator
        else:
            ET.SubElement(run, _w("tab"))
        if location:
            ET.SubElement(ET.SubElement(paragraph, _w("r")), _w("t")).text = location

    DocxTreeSanitizer.sanitize_document(document)

    paragraphs = body.findall(_w("p"))
    for paragraph in paragraphs[:2]:
        assert len(paragraph.findall(f".//{_w('r')}/{_w('tab')}")) == 1
        assert len(paragraph.findall(f"{_w('pPr')}/{_w('tabs')}/{_w('tab')}")) == 1
        assert "Zhejiang, China" in "".join(paragraph.itertext())
    assert not paragraphs[2].findall(f".//{_w('r')}/{_w('tab')}")
    assert paragraphs[2].find(f"{_w('pPr')}/{_w('tabs')}") is None


def test_typography_linter_blocks_trailing_dash_artifacts() -> None:
    passed, issues = TypographyLinter.check_pdf_typography(
        "Clean sentence.\nRendered artifact.-----\n16-bit model."
    )

    assert passed is False
    assert len(issues) == 1