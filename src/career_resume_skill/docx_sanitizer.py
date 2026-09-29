from __future__ import annotations

import re

from lxml import etree as ET

from .text_utils import normalize_sentence_ending

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
            for run in paragraph.iter(_w("r")):
                for tab in list(run.findall(_w("tab"))):
                    run.remove(tab)
            properties = paragraph.find(_w("pPr"))
            if properties is not None:
                for tabs in list(properties.findall(_w("tabs"))):
                    properties.remove(tabs)

    @classmethod
    def _strip_leader_attributes(cls, root: ET.Element) -> None:
        leader = _w("leader")
        for tab in root.iter(_w("tab")):
            tab.attrib.pop(leader, None)
