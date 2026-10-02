from __future__ import annotations

import re

from lxml import etree as ET

from .text_utils import normalize_sentence_ending
from .typography import estimate_string_width

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


class LexicalSanitizer:
    """Normalize injected bullet text without changing supported claim content."""

    _LEADING_BULLETS = re.compile(r"^[\s•\u2022\u25e6\u25aa\u25ab\uf0b7*]+")
    _INVISIBLE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
    _TRAILING_NOISE = re.compile(
        r"[\s\t\r\n\-‐‑‒–—―\u2010-\u2015\u2212\ufe58\ufe63\uff0d._]+$"
    )

    @classmethod
    def clean_text(cls, text: str, language: str | None = None) -> str:
        if not text:
            return ""
        cleaned = cls._INVISIBLE.sub("", text)
        cleaned = cls._LEADING_BULLETS.sub("", cleaned).strip()
        cleaned = cls._TRAILING_NOISE.sub("", cleaned).rstrip()
        detected_language = language or (
            "zh_CN" if re.search(r"[\u4e00-\u9fff]", cleaned) else "en"
        )
        return normalize_sentence_ending(cleaned, detected_language)


class DocxTreeSanitizer:
    """Remove automatic leader behavior while preserving ordinary alignment tabs in styles."""

    @classmethod
    def sanitize_document(
        cls,
        document_xml: ET.Element,
        styles_xml: ET.Element | None = None,
    ) -> None:
        cls._strip_paragraph_tabs(document_xml)
        cls._strip_leader_attributes(document_xml)
        if styles_xml is not None:
            cls._strip_leader_attributes(styles_xml)

    @classmethod
    def _strip_paragraph_tabs(cls, root: ET.Element) -> None:
        for paragraph in root.iter(_w("p")):
            properties = paragraph.find(_w("pPr"))
            tabs = properties.find(_w("tabs")) if properties is not None else None
            right_tabs = [
                tab for tab in tabs.findall(_w("tab"))
                if tab.get(_w("val")) == "right" and tab.get(_w("pos"))
            ] if tabs is not None else []
            if right_tabs and not paragraph.findall(f".//{_w('r')}/{_w('tab')}"):
                runs = list(paragraph.iter(_w("r")))
                for index, run in enumerate(runs[:-1]):
                    text = run.find(_w("t"))
                    if (
                        text is not None and text.text and len(text.text) >= 8
                        and text.text.isspace()
                        and any(next_run.find(_w("t")) is not None
                                and (next_run.find(_w("t")).text or "").strip()
                                for next_run in runs[index + 1:])
                    ):
                        run.replace(text, ET.Element(_w("tab")))
                        break
            run_tabs = paragraph.findall(f".//{_w('r')}/{_w('tab')}")
            nodes = list(paragraph.iter())
            has_right_aligned_content = any(
                any(node.tag == _w("t") and (node.text or "").strip()
                    for node in nodes[nodes.index(tab) + 1:])
                for tab in run_tabs
            )
            if tabs is not None and right_tabs and has_right_aligned_content:
                for tab in list(tabs):
                    if tab is not right_tabs[-1]:
                        tabs.remove(tab)
                cls._separate_crowded_right_tab(paragraph, run_tabs[0], right_tabs[-1])
                continue
            for run in paragraph.iter(_w("r")):
                for tab in list(run.findall(_w("tab"))):
                    run.remove(tab)
            if properties is not None:
                for tabs in list(properties.findall(_w("tabs"))):
                    properties.remove(tabs)

    @classmethod
    def _separate_crowded_right_tab(
        cls, paragraph: ET.Element, run_tab: ET.Element, right_tab: ET.Element
    ) -> None:
        nodes = list(paragraph.iter())
        tab_index = nodes.index(run_tab)
        left_text = "".join(node.text or "" for node in nodes[:tab_index] if node.tag == _w("t"))
        left = re.split(r"\s{32,}", left_text)[-1].strip()
        right = "".join(node.text or "" for node in nodes[tab_index + 1:] if node.tag == _w("t")).strip()
        if not left or not right:
            return
        run = run_tab.getparent()
        if run is None:
            return
        properties = run.find(_w("rPr"))
        size = properties.find(_w("sz")) if properties is not None else None
        fonts = properties.find(_w("rFonts")) if properties is not None else None
        size_pt = int(size.get(_w("val"))) / 2 if size is not None and size.get(_w("val")) else 11.0
        font_name = (fonts.get(_w("ascii")) if fonts is not None else None) or "Times New Roman"
        available_pt = int(right_tab.get(_w("pos"))) / 20
        if (
            estimate_string_width(left, font_name, size_pt, True)
            + estimate_string_width(right, font_name, size_pt, True)
            + 12 > available_pt
        ):
            run.insert(run.index(run_tab), ET.Element(_w("br")))

    @classmethod
    def _strip_leader_attributes(cls, root: ET.Element) -> None:
        leader = _w("leader")
        for tab in root.iter(_w("tab")):
            tab.attrib.pop(leader, None)
