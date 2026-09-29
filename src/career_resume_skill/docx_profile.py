from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .docx_engine import ParagraphRecord, inspect_docx
from .models import ContactInfo, MasterCV, ResumeSection

_SECTION_ALIASES = {
    "education": ("education", "educational background", "学历", "教育背景"),
    "publications": ("publication", "publications", "论文", "发表"),
    "research": ("research", "科研", "research experience"),
    "experience": ("experience", "internship experience", "work experience", "实习", "工作经历"),
    "projects": ("project", "projects", "项目", "project experience"),
    "skills": ("skill", "skills", "other skills", "技能"),
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"(?:\+?\d[\d ()-]{7,}\d)")
_MONTH_NAME = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)"
)
_YEAR_MONTH = r"(?:(?:19|20)\d{2}[./-](?:0?[1-9]|1[0-2])|(?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2})"
_NAMED_MONTH = rf"{_MONTH_NAME}\.?\s+(?:19|20)\d{{2}}"
_DATE_POINT = rf"(?:{_YEAR_MONTH}|{_NAMED_MONTH})"
_DATE_END = rf"(?:{_DATE_POINT}|Present|Current|Now|至今|目前|在职)"
_DATE_SEPARATOR = r"(?:[-–—~]|至|到)"
_DATE_RANGE_RE = re.compile(
    rf"(?:{_DATE_POINT}(?:\s*{_DATE_SEPARATOR}\s*{_DATE_END})?"
    rf"|(?:19|20)\d{{2}}\s*{_DATE_SEPARATOR}\s*{_DATE_END})",
    re.IGNORECASE,
)
_CN_ROLE_WORDS = (
    "工程师", "算法", "开发", "架构师", "专家", "研究员", "实习生", "总监",
    "经理", "负责人", "顾问", "分析师", "助理", "博士后", "硕士", "管培生",
)


def import_docx_as_master_cv(source_path: str | Path) -> dict[str, Any]:
    report = inspect_docx(source_path)
    paragraphs = [paragraph for paragraph in report.paragraphs if paragraph.text.strip()]
    if not paragraphs:
        raise ValueError("DOCX does not contain readable paragraphs")

    name = paragraphs[0].text.strip()
    contact_text = paragraphs[1].text if len(paragraphs) > 1 else ""
    email_match = _EMAIL_RE.search(contact_text)
    phone_match = _PHONE_RE.search(contact_text)
    location = _extract_location(contact_text, email_match.group(0) if email_match else "")
    contact = ContactInfo(
        email=email_match.group(0) if email_match else "unknown@example.invalid",
        phone=phone_match.group(0) if phone_match else None,
        location=location,
    )

    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    evidence_map: dict[str, str] = {}
    source_item_map: dict[str, dict[str, Any]] = {}
    for paragraph in paragraphs[1:]:
        text = paragraph.text.strip()
        section_type = _section_type(text)
        if section_type:
            current = {"type": section_type, "title": text, "items": []}
            sections.append(current)
            continue
        if current is None:
            continue
        if current["type"] == "skills":
            _add_skill_line(current, text)
            continue
        if not current["items"] or _starts_new_item(current["type"], paragraph):
            item = _item_from_paragraph(text, paragraph.node_id)
            current["items"].append(item)
            evidence_map[f"{current['type']}:{len(current['items']) - 1}"] = paragraph.node_id
            source_item_map[paragraph.node_id] = {"bullet_paragraph_ids": []}
        elif _is_role_or_metadata(text):
            item = current["items"][-1]
            if not item.get("organization"):
                item["organization"] = item["title"]
            item["title"] = _without_dates(text).strip() or item["title"]
            item["dates"] = _extract_dates(text)
        else:
            current["items"][-1]["bullets"].append(text)
            source_item_id = current["items"][-1]["source_item_id"]
            source_item_map[source_item_id]["bullet_paragraph_ids"].append(paragraph.node_id)

    skills = _skills_from_section(sections)
    normalized_sections = [
        section for section in sections if section["type"] != "skills" and section["items"]
    ]
    master_cv = MasterCV(
        name=name,
        contact=contact,
        profile="",
        sections=[ResumeSection.model_validate(section) for section in normalized_sections],
        skills=skills,
    )
    return {
        "master_cv": master_cv.model_dump(),
        "source_docx": str(Path(source_path).expanduser().resolve()),
        "paragraph_count": len(paragraphs),
        "evidence_map": evidence_map,
        "source_item_map": source_item_map,
        "layout_manifest": report.to_dict(),
    }


def _section_type(text: str) -> str | None:
    normalized = re.sub(r"[^a-z\u4e00-\u9fff ]", "", text.casefold()).strip()
    normalized = " ".join(normalized.split())
    is_explicit_heading = text.strip().isupper() or normalized in {
        alias.casefold() for aliases in _SECTION_ALIASES.values() for alias in aliases
    }
    if len(normalized) > 60 or not is_explicit_heading:
        return None
    for section_type, aliases in _SECTION_ALIASES.items():
        if any(alias.casefold() == normalized for alias in aliases):
            return section_type
    for section_type, aliases in _SECTION_ALIASES.items():
        if text.strip().isupper() and any(alias.casefold() in normalized for alias in aliases):
            return section_type
    return None


def _item_from_paragraph(text: str, paragraph_id: str) -> dict[str, Any]:
    return {
        "source_item_id": paragraph_id,
        "title": text,
        "organization": "",
        "location": "",
        "dates": "",
        "bullets": [],
    }


def _starts_new_item(section_type: str, paragraph: ParagraphRecord) -> bool:
    text = paragraph.text.strip()
    if section_type == "publications":
        if len(text) > 120:
            return False
        return not _is_role_or_metadata(text)
    if section_type == "education":
        return _looks_like_institution(text) or _has_heading_style(paragraph)
    if section_type == "experience":
        return (
            _looks_like_organization(text) or _has_heading_style(paragraph)
            or _is_emphasized_short_title(paragraph)
        ) and not _is_role_or_metadata(text)
    if section_type == "projects":
        return _has_heading_style(paragraph) or _is_emphasized_short_title(paragraph)
    return False


def _is_role_or_metadata(text: str) -> bool:
    lowered = text.casefold()
    role_words = (
        "author", "member", "intern", "trainee", "owner", "developer", "engineer",
        "researcher", "analyst", "scientist", "manager", "consultant", "candidate",
    )
    return (
        any(word in lowered for word in role_words)
        or any(word in text for word in _CN_ROLE_WORDS)
        or bool(
        _DATE_RANGE_RE.search(text)
        )
    )


def _has_heading_style(paragraph: ParagraphRecord) -> bool:
    style_id = str(paragraph.style.get("style_id") or "").casefold()
    return any(token in style_id for token in ("heading", "title", "subtitle"))


def _is_emphasized_short_title(paragraph: ParagraphRecord) -> bool:
    text = paragraph.text.strip()
    return (
        2 <= len(text) <= 100
        and not text.endswith((".", "。", ";", "；", "!", "?"))
        and any(run.style.get("bold") for run in paragraph.runs)
    )


def _looks_like_institution(text: str) -> bool:
    lowered = text.casefold()
    return any(
        term in lowered
        for term in (
            "university", "college", "institute", "school", "academy",
            "大学", "学院", "研究院", "学府",
        )
    )


def _looks_like_organization(text: str) -> bool:
    lowered = text.casefold()
    organization_words = (
        "university",
        "college",
        "corporation",
        "center",
        "institute",
        "laboratory",
        "technology",
        "technologies",
        "research group",
        "systems",
    )
    company_suffix = re.search(
        r"\b(?:inc\.?|llc|ltd\.?|limited|corp\.?|corporation|group|labs?)\b",
        lowered,
    )
    return company_suffix is not None or any(word in lowered for word in organization_words)


def _extract_dates(text: str) -> str:
    matches = _DATE_RANGE_RE.findall(text)
    return " / ".join(matches)


def _without_dates(text: str) -> str:
    return _DATE_RANGE_RE.sub("", text).strip()


def _add_skill_line(section: dict[str, Any], text: str) -> None:
    if ":" in text:
        group, values = text.split(":", 1)
        section["items"].append({"title": group.strip(), "bullets": [values.strip()]})
    else:
        section["items"].append({"title": "Skills", "bullets": [text]})


def _skills_from_section(sections: list[dict[str, Any]]) -> dict[str, list[str]]:
    skills: dict[str, list[str]] = {}
    for section in sections:
        if section["type"] != "skills":
            continue
        for item in section["items"]:
            group = item["title"]
            values = item.get("bullets", [])
            skills[group] = [
                token.strip()
                for value in values
                for token in _split_skill_values(value)
                if token.strip()
            ]
    return skills


def _split_skill_values(value: str) -> list[str]:
    separators = {",", ";", "|"}
    closing_to_opening = {
        ")": "(", "]": "[", "}": "{", "）": "（", "］": "［", "｝": "｛",
    }
    opening = set(closing_to_opening.values())
    stack: list[str] = []
    values: list[str] = []
    start = 0
    for index, character in enumerate(value):
        if character in opening:
            stack.append(character)
        elif character in closing_to_opening:
            expected = closing_to_opening[character]
            if stack and stack[-1] == expected:
                stack.pop()
        elif character in separators and not stack:
            values.append(value[start:index])
            start = index + 1
    values.append(value[start:])
    return values


def _extract_location(text: str, email: str) -> str | None:
    without_contact = text.replace(email, "") if email else text
    without_phone = _PHONE_RE.sub("", without_contact)
    candidates = [part.strip(" |,-") for part in without_phone.split("|")]
    return candidates[-1] if candidates and candidates[-1] else None
