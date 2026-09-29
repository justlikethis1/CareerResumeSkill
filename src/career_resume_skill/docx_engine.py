from __future__ import annotations

import base64
import copy
import json
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from lxml import etree as ET
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import DecodedStreamObject

from .docx_sanitizer import DocxTreeSanitizer, LexicalSanitizer
from .tools import find_libreoffice, find_microsoft_word
from .typography import estimate_string_width, estimate_wrapped_line_count, resolved_font_path

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"w": W_NS, "wp": WP_NS, "a": A_NS, "r": R_NS, "pr": PR_NS}
_PPR_CHILD_ORDER = (
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
    "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens",
    "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE",
    "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind",
    "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection",
    "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr",
    "sectPr", "pPrChange",
)


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"
class DocxLayoutError(RuntimeError):
    """Base error for safe DOCX inspection, replacement, or conversion."""


class ReplacementNotFoundError(DocxLayoutError):
    pass


class TextLengthBudgetError(DocxLayoutError):
    pass


def calculate_docx_layout_budget(
    source_path: str | Path, resources_dir: str | Path | None = None
) -> dict[str, Any]:
    document = inspect_docx(source_path, resources_dir)
    paragraphs: list[dict[str, Any]] = []
    for paragraph in document.paragraphs:
        if not paragraph.text.strip():
            continue
        measurements = _paragraph_geometry(document, paragraph)
        measurements.update({"paragraph_id": paragraph.node_id, "source_text": paragraph.text})
        paragraphs.append(measurements)
    return {
        "method": "Pillow font metrics at 96 DPI; page width minus margins (table-cell widths are not resolved)",
        "page_width_pt": (document.layout.get("page_width_twips") or 12240) / 20,
        "usable_width_pt": paragraphs[0]["available_width_pt"] if paragraphs else None,
        "target_line_occupancy_ratio": [0.85, 0.92],
        "paragraphs": paragraphs,
    }


def _paragraph_geometry(document: DocxLayoutDocument, paragraph: ParagraphRecord) -> dict[str, Any]:
    page_width_twips = document.layout.get("page_width_twips") or 12240
    margins = document.layout.get("margins_twips") or {}
    margin_left = margins.get("left") or 1440
    margin_right = margins.get("right") or 1440
    columns = max(1, int(document.layout.get("columns", 1)))
    available_width_pt = max(36.0, (page_width_twips - margin_left - margin_right) / 20 / columns)
    cell_width_twips = paragraph.style.get("table_cell_width_twips")
    if cell_width_twips:
        available_width_pt = min(available_width_pt, max(36.0, cell_width_twips / 20))
    elif paragraph.table_path:
        available_width_pt = max(
            36.0, available_width_pt / max(1, paragraph.style.get("table_cell_count", 1))
        )
    style_id = paragraph.style.get("style_id") or "Normal"
    style_catalog = document.layout.get("styles", {})
    style = style_catalog.get(style_id, {})
    normal_style = style_catalog.get("Normal", {})
    run_style = paragraph.runs[0].style if paragraph.runs else {}
    inherited_style = style.get("run_style") or normal_style.get("run_style", {})
    contains_cjk = bool(re.search(r"[\u2e80-\u9fff\uf900-\ufaff]", paragraph.text))
    east_asian_font = (
        run_style.get("font_family_east_asia")
        or inherited_style.get("font_family_east_asia")
    )
    font_name = (
        (east_asian_font if contains_cjk else None)
        or run_style.get("font_family")
        or inherited_style.get("font_family")
        or "Arial"
    )
    font_size_pt = (
        run_style.get("font_size_pt")
        or inherited_style.get("font_size_pt")
        or 10.0
    )
    bold = bool(run_style.get("bold") or inherited_style.get("bold"))
    source_width_pt = estimate_string_width(paragraph.text, font_name, font_size_pt, bold)
    source_lines = estimate_wrapped_line_count(
        paragraph.text, available_width_pt, font_name, font_size_pt, bold
    )
    return {
        "font_name": font_name,
        "resolved_font_path": resolved_font_path(font_name, font_size_pt, bold),
        "font_size_pt": font_size_pt,
        "bold": bold,
        "available_width_pt": round(available_width_pt, 2),
        "table_cell_width_twips": cell_width_twips,
        "source_text_width_pt": round(source_width_pt, 2),
        "estimated_source_lines": source_lines,
        "target_line_width_pt": round(available_width_pt * 0.88, 2),
        "explicit_space_after_twips": paragraph.style.get("spacing_after_twips"),
        "explicit_line_spacing": paragraph.style.get("line_spacing"),
        "explicit_line_rule": paragraph.style.get("line_spacing_rule"),
    }


@dataclass(frozen=True)
class TextNode:
    node_id: str
    text: str
    run_index: int
    style: dict[str, Any]


@dataclass(frozen=True)
class ParagraphRecord:
    node_id: str
    text: str
    style: dict[str, Any]
    runs: list[TextNode]
    table_path: list[int]


@dataclass(frozen=True)
class ImageRecord:
    relationship_id: str
    target: str
    package_path: str
    anchor_type: str
    width_emu: int | None
    height_emu: int | None
    paragraph_id: str | None
    extracted_path: str | None
    position_horizontal: dict[str, Any] | None = None
    position_vertical: dict[str, Any] | None = None
    wrap_type: str | None = None


@dataclass(frozen=True)
class TextBoxRecord:
    text: str
    anchor_type: str
    width_emu: int | None
    height_emu: int | None
    position_horizontal: dict[str, Any] | None
    position_vertical: dict[str, Any] | None
    paragraph_id: str | None


class DocxLayoutDocument:
    def __init__(
        self,
        source_path: Path,
        paragraphs: list[ParagraphRecord],
        images: list[ImageRecord],
        text_boxes: list[TextBoxRecord],
        layout: dict[str, Any],
        resources_dir: Path,
        owns_resources_dir: bool = False,
    ) -> None:
        self.source_path = source_path
        self.paragraphs = paragraphs
        self.images = images
        self.text_boxes = text_boxes
        self.layout = layout
        self.resources_dir = resources_dir
        self._owns_resources_dir = owns_resources_dir

    def close(self) -> None:
        if self._owns_resources_dir:
            shutil.rmtree(self.resources_dir, ignore_errors=True)
            self._owns_resources_dir = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        if getattr(self, "_owns_resources_dir", False):
            self.close()

    @property
    def paragraph_map(self) -> dict[str, ParagraphRecord]:
        return {paragraph.node_id: paragraph for paragraph in self.paragraphs}

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path.resolve()),
            "resources_dir": str(self.resources_dir.resolve()),
            "layout": self.layout,
            "paragraphs": [
                {
                    "node_id": paragraph.node_id,
                    "text": paragraph.text,
                    "style": paragraph.style,
                    "table_path": paragraph.table_path,
                    "runs": [
                        {
                            "node_id": run.node_id,
                            "text": run.text,
                            "run_index": run.run_index,
                            "style": run.style,
                        }
                        for run in paragraph.runs
                    ],
                }
                for paragraph in self.paragraphs
            ],
            "images": [
                {
                    "relationship_id": image.relationship_id,
                    "target": image.target,
                    "package_path": image.package_path,
                    "anchor_type": image.anchor_type,
                    "width_emu": image.width_emu,
                    "height_emu": image.height_emu,
                    "paragraph_id": image.paragraph_id,
                    "extracted_path": image.extracted_path,
                    "position_horizontal": image.position_horizontal,
                    "position_vertical": image.position_vertical,
                    "wrap_type": image.wrap_type,
                }
                for image in self.images
            ],
            "text_boxes": [
                {
                    "text": text_box.text,
                    "anchor_type": text_box.anchor_type,
                    "width_emu": text_box.width_emu,
                    "height_emu": text_box.height_emu,
                    "position_horizontal": text_box.position_horizontal,
                    "position_vertical": text_box.position_vertical,
                    "paragraph_id": text_box.paragraph_id,
                }
                for text_box in self.text_boxes
            ],
        }

    def write_manifest(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return output_path


def inspect_docx(source_path: str | Path, resources_dir: str | Path | None = None) -> DocxLayoutDocument:
    source = Path(source_path).expanduser().resolve()
    if source.suffix.casefold() != ".docx" or not source.is_file():
        raise DocxLayoutError(f"DOCX source does not exist or is not a .docx file: {source}")
    owns_resources_dir = resources_dir is None
    resource_root = (
        Path(resources_dir).expanduser().resolve()
        if resources_dir
        else Path(tempfile.mkdtemp(prefix="career-resume-docx-"))
    )
    resource_root.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(source) as package:
            try:
                document_xml = ET.fromstring(package.read("word/document.xml"))
                relationships = _read_relationships(package)
            except KeyError as error:
                raise DocxLayoutError(f"Invalid DOCX package: missing {error.args[0]}") from error
            paragraphs = _extract_paragraphs(document_xml)
            images = _extract_images(package, document_xml, relationships, resource_root, paragraphs)
            text_boxes = _extract_text_boxes(document_xml, paragraphs)
            layout = _extract_layout(document_xml)
            layout["stories"] = _extract_header_footer_stories(package)
            layout["styles"] = _extract_style_catalog(package)
    except Exception:
        if owns_resources_dir:
            shutil.rmtree(resource_root, ignore_errors=True)
        raise
    return DocxLayoutDocument(
        source, paragraphs, images, text_boxes, layout, resource_root, owns_resources_dir
    )


def inject_docx_text(
    source_path: str | Path,
    output_path: str | Path,
    replacements: dict[str, str],
    *,
    enforce_length_budget: bool = True,
    normalize_body_italic: bool = False,
    normalize_list_bullets: bool = False,
) -> Path:
    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if source == output:
        raise DocxLayoutError("DOCX output_path must differ from source_path")
    document = inspect_docx(source)
    paragraph_map = document.paragraph_map
    missing = sorted(set(replacements) - set(paragraph_map))
    if missing:
        raise ReplacementNotFoundError(f"Unknown paragraph IDs: {missing}")
    for node_id, replacement in replacements.items():
        if enforce_length_budget and paragraph_map[node_id].text.strip():
            geometry = _paragraph_geometry(document, paragraph_map[node_id])
            source_lines = geometry["estimated_source_lines"]
            replacement_lines = estimate_wrapped_line_count(
                replacement,
                geometry["available_width_pt"],
                geometry["font_name"],
                geometry["font_size_pt"],
                geometry["bold"],
            )
            maximum_lines = max(2, source_lines)
            if replacement_lines > maximum_lines:
                raise TextLengthBudgetError(
                    f"Replacement for {node_id} needs {replacement_lines} rendered lines; "
                    f"the physical layout budget is {maximum_lines} lines at "
                    f"{geometry['available_width_pt']:.1f} pt width"
                )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(f".{output.name}.tmp")
    try:
        with zipfile.ZipFile(source, "r") as source_zip:
            document_xml = ET.fromstring(source_zip.read("word/document.xml"))
            _require_single_document_body(document_xml)
            numbering_xml = None
            bullet_num_id = None
            if normalize_list_bullets and "word/numbering.xml" in source_zip.namelist():
                numbering_xml, bullet_num_id = _create_standard_bullet_numbering(
                    source_zip.read("word/numbering.xml")
                )
            _apply_replacements(
                document_xml, replacements, normalize_body_italic, bullet_num_id
            )
            with zipfile.ZipFile(temporary_output, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
                for item in source_zip.infolist():
                    if item.filename == "word/document.xml":
                        payload = ET.tostring(document_xml, encoding="utf-8", xml_declaration=True)
                    elif item.filename == "word/numbering.xml" and numbering_xml is not None:
                        payload = numbering_xml
                    else:
                        payload = source_zip.read(item.filename)
                    output_zip.writestr(item, payload)
        temporary_output.replace(output)
    finally:
        if temporary_output.exists():
            temporary_output.unlink()
    return output


def inject_docx_bullet_groups(
    source_path: str | Path,
    output_path: str | Path,
    groups: dict[str, dict[str, list[str]]],
    *,
    normalize_body_italic: bool = True,
    normalize_list_bullets: bool = True,
    compact_spacing: bool = False,
    compact_level: int | None = None,
    protect_headings: bool = True,
) -> Path:
    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    if source == output:
        raise DocxLayoutError("DOCX output_path must differ from source_path")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(f".{output.name}.tmp")
    try:
        with zipfile.ZipFile(source, "r") as source_zip:
            document_xml = ET.fromstring(source_zip.read("word/document.xml"))
            _require_single_document_body(document_xml)
            records = _extract_paragraphs(document_xml)
            elements = list(document_xml.iter(_tag(W_NS, "p")))
            paragraph_map = {
                record.node_id: element for record, element in zip(records, elements)
            }
            numbering_xml = None
            bullet_num_id = None
            if normalize_list_bullets and "word/numbering.xml" in source_zip.namelist():
                numbering_xml, bullet_num_id = _create_standard_bullet_numbering(
                    source_zip.read("word/numbering.xml")
                )
            style_catalog = _extract_style_catalog(source_zip)
            styles_xml = ET.fromstring(source_zip.read("word/styles.xml")) if "word/styles.xml" in source_zip.namelist() else None
            tab_free_styles: dict[str, str] = {}
            style_tab_positions = _extract_style_tab_positions(
                source_zip.read("word/styles.xml")
            ) if "word/styles.xml" in source_zip.namelist() else {}
            inherited_tab_positions = tuple(dict.fromkeys(
                position
                for positions in style_tab_positions.values()
                for position in positions
            ))
            if "word/numbering.xml" in source_zip.namelist():
                inherited_tab_positions = tuple(dict.fromkeys(
                    (*inherited_tab_positions, *(
                        position
                        for tab in ET.fromstring(source_zip.read("word/numbering.xml")).iter(
                            _tag(W_NS, "tab")
                        )
                        if (position := tab.get(_tag(W_NS, "pos")))
                    ))
                ))
            for group in groups.values():
                paragraph_ids = group.get("paragraph_ids", [])
                bullets = group.get("bullets", [])
                targets = [paragraph_map[node_id] for node_id in paragraph_ids if node_id in paragraph_map]
                if not targets:
                    continue
                while len(targets) < len(bullets):
                    clone = copy.deepcopy(targets[-1])
                    _remove_paragraph_section_properties(clone)
                    targets[-1].addnext(clone)
                    targets.append(clone)
                for redundant in targets[len(bullets):]:
                    parent = redundant.getparent()
                    if parent is not None:
                        if (
                            parent.tag == _tag(W_NS, "tc")
                            and len(parent.findall(_tag(W_NS, "p"))) <= 1
                        ):
                            _replace_paragraph_text(
                                redundant, "", normalize_body_italic, None
                            )
                        else:
                            parent.remove(redundant)
                for paragraph, bullet in zip(targets, bullets):
                    source_style_id = _paragraph_style_id(paragraph)
                    if styles_xml is not None:
                        clean_style_id = _ensure_tab_free_style(
                            styles_xml, source_style_id, tab_free_styles
                        )
                        _set_paragraph_style(paragraph, clean_style_id)
                    _replace_paragraph_text(
                        paragraph,
                        bullet,
                        normalize_body_italic,
                        bullet_num_id,
                        inherited_tab_positions,
                    )
            DocxTreeSanitizer.sanitize_document(document_xml, styles_xml)
            _ensure_heading_keep_next(document_xml, style_catalog)
            level = compact_level if compact_level is not None else (1 if compact_spacing else 0)
            if level not in {0, 1, 2}:
                raise ValueError("compact_level must be 0, 1, or 2")
            if level:
                _compact_docx_layout(
                    document_xml, style_catalog, level=level, protect_headings=protect_headings
                )
            with zipfile.ZipFile(temporary_output, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
                for item in source_zip.infolist():
                    if item.filename == "word/document.xml":
                        payload = ET.tostring(document_xml, encoding="utf-8", xml_declaration=True)
                    elif item.filename == "word/styles.xml" and styles_xml is not None:
                        payload = ET.tostring(styles_xml, encoding="utf-8", xml_declaration=True)
                    elif item.filename == "word/numbering.xml" and numbering_xml is not None:
                        payload = numbering_xml
                    else:
                        payload = source_zip.read(item.filename)
                    output_zip.writestr(item, payload)
        temporary_output.replace(output)
    finally:
        if temporary_output.exists():
            temporary_output.unlink()
    return output


def _compact_bullet_spacing(paragraph: ET.Element) -> None:
    properties = paragraph.find(_tag(W_NS, "pPr"))
    spacing = properties.find(_tag(W_NS, "spacing")) if properties is not None else None
    if spacing is None:
        return
    after = spacing.get(_tag(W_NS, "after"))
    if after is not None and after.isdecimal() and int(after) >= 50:
        spacing.set(_tag(W_NS, "after"), str(max(36, int(after) - 14)))
    line = spacing.get(_tag(W_NS, "line"))
    rule = spacing.get(_tag(W_NS, "lineRule"), "auto")
    if line is not None and line.isdecimal() and rule == "auto" and int(line) >= 240:
        spacing.set(_tag(W_NS, "line"), str(max(230, int(line) - 10)))


def _ensure_heading_keep_next(
    document_xml: ET.Element, style_catalog: dict[str, dict[str, Any]]
) -> None:
    for paragraph in document_xml.iter(_tag(W_NS, "p")):
        properties = paragraph.find(_tag(W_NS, "pPr"))
        style_node = properties.find(_tag(W_NS, "pStyle")) if properties is not None else None
        style_id = style_node.get(_tag(W_NS, "val"), "") if style_node is not None else ""
        style = style_catalog.get(style_id, {})
        label = f"{style_id} {style.get('name', '')}".casefold()
        paragraph_text = "".join(
            node.text or "" for node in paragraph.iter(_tag(W_NS, "t"))
        ).strip()
        text_heading = (
            len(paragraph_text) <= 60
            and paragraph_text == paragraph_text.upper()
            and any(character.isalpha() for character in paragraph_text)
        )
        if not text_heading and not any(
            marker in label for marker in ("heading", "title", "subtitle")
        ):
            continue
        if properties is None:
            properties = ET.Element(_tag(W_NS, "pPr"))
            paragraph.insert(0, properties)
        keep_next = properties.find(_tag(W_NS, "keepNext"))
        if keep_next is None:
            keep_next = ET.Element(_tag(W_NS, "keepNext"))
            _insert_ppr_child_in_schema_order(properties, keep_next)
        keep_next.set(_tag(W_NS, "val"), "true")
        spacing = properties.find(_tag(W_NS, "spacing"))
        if spacing is None:
            spacing = ET.Element(_tag(W_NS, "spacing"))
            _insert_ppr_child_in_schema_order(properties, spacing)
        after = spacing.get(_tag(W_NS, "after"))
        if after is None or (after.isdecimal() and int(after) < 120):
            spacing.set(_tag(W_NS, "after"), "120")


def _style_spacing_values(
    style_id: str, style_catalog: dict[str, dict[str, Any]]
) -> dict[str, str]:
    values: dict[str, str] = {}
    visited: set[str] = set()
    current_id = style_id or "Normal"
    while current_id and current_id not in visited:
        visited.add(current_id)
        style = style_catalog.get(current_id, {})
        paragraph_style = style.get("paragraph_style", {})
        for source, target in (
            ("spacing_after_twips", "after"),
            ("spacing_before_twips", "before"),
            ("line_spacing", "line"),
            ("line_spacing_rule", "lineRule"),
        ):
            if target not in values and paragraph_style.get(source) is not None:
                values[target] = str(paragraph_style[source])
        current_id = str(style.get("based_on") or "")
    return values


def _compact_docx_layout(
    document_xml: ET.Element,
    style_catalog: dict[str, dict[str, Any]],
    *,
    level: int = 1,
    protect_headings: bool = True,
) -> None:
    if level not in {1, 2}:
        raise ValueError("compact layout level must be 1 or 2")
    for paragraph in document_xml.iter(_tag(W_NS, "p")):
        properties = paragraph.find(_tag(W_NS, "pPr"))
        style_node = properties.find(_tag(W_NS, "pStyle")) if properties is not None else None
        style_id = style_node.get(_tag(W_NS, "val"), "Normal") if style_node is not None else "Normal"
        style = style_catalog.get(style_id, {})
        style_label = f"{style_id} {style.get('name', '')}".casefold()
        is_heading = any(marker in style_label for marker in ("heading", "title", "subtitle"))
        inherited = _style_spacing_values(style_id, style_catalog)
        spacing = properties.find(_tag(W_NS, "spacing")) if properties is not None else None
        effective = {
            key: spacing.get(_tag(W_NS, key)) if spacing is not None else None
            for key in ("after", "before", "line", "lineRule")
        }
        for key, value in inherited.items():
            if effective[key] is None:
                effective[key] = value
        changes: dict[str, str] = {}
        for key, threshold, reduction, floor in (
            ("after", 40, 40, 20),
            ("before", 60, 40, 20),
        ):
            value = effective[key]
            if value and value.isdecimal() and int(value) > threshold:
                changes[key] = str(max(floor, int(value) - reduction))
        line_rule = effective["lineRule"]
        line = effective["line"]
        if level == 1 and line and line.isdecimal() and line_rule in (None, "auto") and int(line) > 225:
            changes["line"] = "225"
            changes["lineRule"] = "auto"
        elif level == 2:
            changes["line"] = "220"
            changes["lineRule"] = "auto"
            if is_heading and protect_headings:
                before = effective["before"]
                after = effective["after"]
                changes["before"] = str(max(60, int(before) if before and before.isdecimal() else 0))
                changes["after"] = str(max(30, int(after) if after and after.isdecimal() else 0))
        if not changes:
            continue
        if properties is None:
            properties = ET.Element(_tag(W_NS, "pPr"))
            paragraph.insert(0, properties)
        if spacing is None:
            spacing = ET.Element(_tag(W_NS, "spacing"))
            _insert_ppr_child_in_schema_order(properties, spacing)
        for key, value in changes.items():
            spacing.set(_tag(W_NS, key), value)
    if level == 2:
        _compact_section_margins(document_xml)


def _compact_section_margins(document_xml: ET.Element) -> None:
    for page_margins in document_xml.iter(_tag(W_NS, "pgMar")):
        for side in ("top", "bottom"):
            value = page_margins.get(_tag(W_NS, side))
            if value is not None and value.isdecimal():
                page_margins.set(_tag(W_NS, side), str(max(540, int(value) - 144)))


def convert_docx_to_pdf(docx_path: str | Path, output_dir: str | Path | None = None) -> Path:
    source = Path(docx_path).expanduser().resolve()
    target_dir = Path(output_dir).expanduser().resolve() if output_dir else source.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / f"{source.stem}.pdf"
    if find_microsoft_word():
        return _deduplicate_pdf_pages(
            _sanitize_pdf_dash_fillers(_convert_docx_with_word(source, pdf_path))
        )
    soffice = find_libreoffice()
    if not soffice:
        raise DocxLayoutError(
            "LibreOffice headless executable not found. Install LibreOffice to export DOCX to PDF."
        )
    with tempfile.TemporaryDirectory(prefix="career-resume-lo-") as profile_dir:
        process = subprocess.run(
            [
                soffice,
                "--headless",
                "--invisible",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--nolockcheck",
                f"-env:UserInstallation={Path(profile_dir).as_uri()}",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(target_dir),
                str(source),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
    if process.returncode != 0 or not pdf_path.exists():
        log = ((process.stdout or "") + "\n" + (process.stderr or "")).strip()
        raise DocxLayoutError(f"DOCX to PDF conversion failed:\n{log[-4000:]}")
    return _deduplicate_pdf_pages(_sanitize_pdf_dash_fillers(pdf_path))


def _sanitize_pdf_dash_fillers(pdf_path: Path) -> Path:
    """Remove standalone dash-only text objects emitted as DOCX tab-leader artifacts."""
    try:
        PdfReader(str(pdf_path))
    except (PdfReadError, OSError):
        return pdf_path
    writer = PdfWriter(clone_from=str(pdf_path))
    changed = False
    array_pattern = re.compile(
        rb"\[((?:\s*\(-+\)\s*|\s*-?\d+(?:\.\d+)?\s*)+)\]\s*TJ"
    )

    def strip_dash_array(match: re.Match[bytes]) -> bytes:
        body = match.group(1)
        dash_count = sum(len(token) - 2 for token in re.findall(rb"\(-+\)", body))
        return b" " if dash_count >= 2 else match.group(0)

    for page in writer.pages:
        contents = page.get_contents()
        if contents is not None:
            raw = contents.get_data()
            cleaned = array_pattern.sub(strip_dash_array, raw)
            if cleaned != raw:
                stream = DecodedStreamObject()
                stream.set_data(cleaned)
                page.replace_contents(stream)
                changed = True
    if not changed:
        return pdf_path
    temporary = pdf_path.with_name(f".{pdf_path.name}.sanitized.tmp")
    try:
        with temporary.open("wb") as stream:
            writer.write(stream)
        temporary.replace(pdf_path)
    finally:
        temporary.unlink(missing_ok=True)
    return pdf_path


def _deduplicate_pdf_pages(pdf_path: Path) -> Path:
    """Remove adjacent exact-text duplicate pages emitted by a DOCX converter."""
    try:
        reader = PdfReader(str(pdf_path))
    except (PdfReadError, OSError):
        return pdf_path
    pages = list(reader.pages)
    if len(pages) < 2:
        return pdf_path
    retained = []
    previous_signature: str | None = None
    changed = False
    for page in pages:
        text = " ".join((page.extract_text() or "").split())
        signature = text
        if not signature:
            contents = page.get_contents()
            signature = contents.get_data().hex() if contents is not None else ""
        if signature and signature == previous_signature:
            changed = True
            continue
        retained.append(page)
        previous_signature = signature
    if not changed:
        return pdf_path
    writer = PdfWriter()
    for page in retained:
        writer.add_page(page)
    temporary = pdf_path.with_name(f".{pdf_path.name}.deduplicated.tmp")
    try:
        with temporary.open("wb") as stream:
            writer.write(stream)
        temporary.replace(pdf_path)
    finally:
        temporary.unlink(missing_ok=True)
    return pdf_path


def _convert_docx_with_word(source: Path, pdf_path: Path) -> Path:
        source_literal = str(source).replace("'", "''")
        pdf_literal = str(pdf_path).replace("'", "''")
        script = f"""
$ErrorActionPreference = 'Stop'
$word = $null
$document = $null
try {{
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $document = $word.Documents.Open('{source_literal}')
    $document.ExportAsFixedFormat('{pdf_literal}', 17)
}} finally {{
    if ($null -ne $document) {{ $document.Close($false) }}
    if ($null -ne $word) {{ $word.Quit() }}
}}
"""
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        process = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
        )
        if process.returncode != 0 or not pdf_path.exists():
                log = ((process.stdout or "") + "\n" + (process.stderr or "")).strip()
                raise DocxLayoutError(f"Microsoft Word PDF conversion failed:\n{log[-4000:]}")
        return pdf_path


def _read_relationships(package: zipfile.ZipFile) -> dict[str, str]:
    root = ET.fromstring(package.read("word/_rels/document.xml.rels"))
    return {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in root.findall(_tag(PR_NS, "Relationship"))
        if relationship.attrib.get("Type", "").endswith("/image")
    }


def _extract_paragraphs(document_xml: ET.Element) -> list[ParagraphRecord]:
    paragraphs: list[ParagraphRecord] = []
    for paragraph_index, paragraph in enumerate(document_xml.iter(_tag(W_NS, "p"))):
        table_path = _table_path(paragraph)
        node_id = _paragraph_id(paragraph_index, table_path)
        runs: list[TextNode] = []
        text_parts: list[str] = []
        for run_index, run in enumerate(paragraph.findall(f".//{_tag(W_NS, 'r')}")):
            texts = [node.text or "" for node in run.findall(_tag(W_NS, "t"))]
            run_text = "".join(texts)
            if not run_text:
                continue
            run_id = f"{node_id}:run:{run_index}"
            runs.append(TextNode(run_id, run_text, run_index, _run_style(run)))
            text_parts.append(run_text)
        paragraph_style = _paragraph_style(paragraph)
        if table_path:
            paragraph_style["table_cell_width_twips"] = _table_cell_width_twips(paragraph)
            cell = next(paragraph.iterancestors(_tag(W_NS, "tc")), None)
            row = cell.getparent() if cell is not None else None
            paragraph_style["table_cell_count"] = (
                len(row.findall(_tag(W_NS, "tc"))) if row is not None else 1
            )
        paragraphs.append(
            ParagraphRecord(node_id, "".join(text_parts), paragraph_style, runs, table_path)
        )
    return paragraphs


def _table_cell_width_twips(paragraph: ET.Element) -> int | None:
    cell = next(paragraph.iterancestors(_tag(W_NS, "tc")), None)
    if cell is None:
        return None
    properties = cell.find(_tag(W_NS, "tcPr"))
    width = properties.find(_tag(W_NS, "tcW")) if properties is not None else None
    if width is not None and width.get(_tag(W_NS, "type")) == "dxa":
        amount = _int_attr(width, "w")
        if amount and amount > 0:
            return amount
    row = cell.getparent()
    table = next(cell.iterancestors(_tag(W_NS, "tbl")), None)
    if row is None or table is None:
        return None
    cells = row.findall(_tag(W_NS, "tc"))
    grid = table.find(_tag(W_NS, "tblGrid"))
    grid_columns = grid.findall(_tag(W_NS, "gridCol")) if grid is not None else []
    if grid_columns:
        offset = 0
        for sibling in cells[:cells.index(cell)]:
            sibling_properties = sibling.find(_tag(W_NS, "tcPr"))
            span = sibling_properties.find(_tag(W_NS, "gridSpan")) if sibling_properties is not None else None
            offset += int(span.get(_tag(W_NS, "val"), "1")) if span is not None else 1
        span = properties.find(_tag(W_NS, "gridSpan")) if properties is not None else None
        count = int(span.get(_tag(W_NS, "val"), "1")) if span is not None else 1
        widths = [_int_attr(column, "w") for column in grid_columns[offset:offset + count]]
        if widths and all(value and value > 0 for value in widths):
            return sum(value for value in widths if value is not None)
    table_properties = table.find(_tag(W_NS, "tblPr"))
    table_width = table_properties.find(_tag(W_NS, "tblW")) if table_properties is not None else None
    if table_width is not None and table_width.get(_tag(W_NS, "type")) == "dxa" and cells:
        amount = _int_attr(table_width, "w")
        if amount and amount > 0:
            return amount // len(cells)
    return None


def _paragraph_id(index: int, table_path: list[int]) -> str:
    location = ".".join(str(value) for value in table_path) if table_path else "body"
    return f"p:{index}:{location}"


def _table_path(element: ET.Element) -> list[int]:
    path: list[int] = []
    current = element
    while current is not None:
        parent = current.getparent()
        if parent is None:
            break
        if parent.tag in {
            _tag(W_NS, "tbl"),
            _tag(W_NS, "tr"),
            _tag(W_NS, "tc"),
        }:
            path.append(list(parent).index(current))
        current = parent
    return list(reversed(path))


def _run_style(run: ET.Element) -> dict[str, Any]:
    properties = run.find(_tag(W_NS, "rPr"))
    if properties is None:
        return {}
    fonts = properties.find(_tag(W_NS, "rFonts"))
    size = properties.find(_tag(W_NS, "sz"))
    color = properties.find(_tag(W_NS, "color"))
    spacing = properties.find(_tag(W_NS, "spacing"))
    return {
        "font_family": (fonts.attrib.get(_tag(W_NS, "ascii")) if fonts is not None else None),
        "font_family_east_asia": (
            fonts.attrib.get(_tag(W_NS, "eastAsia")) if fonts is not None else None
        ),
        "font_size_pt": float(size.attrib[_tag(W_NS, "val")]) / 2 if size is not None else None,
        "bold": _run_property_enabled(properties, "b"),
        "italic": _run_property_enabled(properties, "i"),
        "color_hex": color.attrib.get(_tag(W_NS, "val")) if color is not None else None,
        "character_spacing_twips": (
            spacing.attrib.get(_tag(W_NS, "val")) if spacing is not None else None
        ),
    }


def _run_property_enabled(properties: ET.Element, name: str) -> bool:
    element = properties.find(_tag(W_NS, name))
    if element is None:
        return False
    return element.get(_tag(W_NS, "val"), "true").casefold() not in {"0", "false", "off"}


def _paragraph_style(paragraph: ET.Element) -> dict[str, Any]:
    properties = paragraph.find(_tag(W_NS, "pPr"))
    if properties is None:
        return {}
    spacing = properties.find(_tag(W_NS, "spacing"))
    alignment = properties.find(_tag(W_NS, "jc"))
    style = properties.find(_tag(W_NS, "pStyle"))
    return {
        "style_id": style.attrib.get(_tag(W_NS, "val")) if style is not None else None,
        "alignment": alignment.attrib.get(_tag(W_NS, "val")) if alignment is not None else None,
        "spacing_before_twips": (
            spacing.attrib.get(_tag(W_NS, "before")) if spacing is not None else None
        ),
        "spacing_after_twips": (
            spacing.attrib.get(_tag(W_NS, "after")) if spacing is not None else None
        ),
        "line_spacing": spacing.attrib.get(_tag(W_NS, "line")) if spacing is not None else None,
        "line_spacing_rule": spacing.attrib.get(_tag(W_NS, "lineRule")) if spacing is not None else None,
    }


def _extract_layout(document_xml: ET.Element) -> dict[str, Any]:
    sections = document_xml.findall(f".//{_tag(W_NS, 'sectPr')}")
    if not sections:
        return {"columns": 1}
    section_records = [_section_layout(section) for section in sections]
    return {**section_records[0], "sections": section_records}


def _section_layout(section: ET.Element) -> dict[str, Any]:
    page_size = section.find(_tag(W_NS, "pgSz"))
    margins = section.find(_tag(W_NS, "pgMar"))
    columns = section.find(_tag(W_NS, "cols"))
    return {
        "columns": int(columns.attrib.get(_tag(W_NS, "num"), "1")) if columns is not None else 1,
        "page_width_twips": _int_attr(page_size, "w"),
        "page_height_twips": _int_attr(page_size, "h"),
        "margins_twips": {
            key: _int_attr(margins, key) for key in ("top", "right", "bottom", "left")
        },
    }


def _extract_style_catalog(package: zipfile.ZipFile) -> dict[str, dict[str, Any]]:
    try:
        styles_xml = ET.fromstring(package.read("word/styles.xml"))
    except KeyError:
        return {}
    catalog: dict[str, dict[str, Any]] = {}
    for style in styles_xml.findall(_tag(W_NS, "style")):
        style_id = style.attrib.get(_tag(W_NS, "styleId"))
        if not style_id:
            continue
        name = style.find(_tag(W_NS, "name"))
        based_on = style.find(_tag(W_NS, "basedOn"))
        catalog[style_id] = {
            "type": style.attrib.get(_tag(W_NS, "type")),
            "name": name.attrib.get(_tag(W_NS, "val")) if name is not None else None,
            "based_on": based_on.attrib.get(_tag(W_NS, "val")) if based_on is not None else None,
            "run_style": _run_style(style),
            "paragraph_style": _paragraph_style(style),
        }
    return catalog


def _int_attr(element: ET.Element | None, name: str) -> int | None:
    if element is None:
        return None
    value = element.attrib.get(_tag(W_NS, name))
    return int(value) if value is not None else None


def _extract_images(
    package: zipfile.ZipFile,
    document_xml: ET.Element,
    relationships: dict[str, str],
    resources_dir: Path,
    paragraphs: list[ParagraphRecord],
) -> list[ImageRecord]:
    tree = document_xml.getroottree()
    paragraph_by_path = {
        tree.getpath(paragraph): record
        for paragraph, record in zip(document_xml.iter(_tag(W_NS, "p")), paragraphs)
    }
    images: list[ImageRecord] = []
    for drawing in document_xml.iter(_tag(W_NS, "drawing")):
        blip = drawing.find(f".//{_tag(A_NS, 'blip')}")
        if blip is None:
            continue
        relationship_id = blip.attrib.get(_tag(R_NS, "embed"), "")
        target = relationships.get(relationship_id)
        if not target:
            continue
        package_path = posixpath.normpath(posixpath.join("word", target))
        anchor = drawing.find(_tag(WP_NS, "anchor"))
        inline = drawing.find(_tag(WP_NS, "inline"))
        container = anchor if anchor is not None else inline
        extent = container.find(_tag(WP_NS, "extent")) if container is not None else None
        output = resources_dir / Path(package_path).name
        try:
            output.write_bytes(package.read(package_path))
        except KeyError:
            continue
        images.append(
            ImageRecord(
                relationship_id,
                target,
                package_path,
                "floating" if anchor is not None else "inline",
                int(extent.attrib.get("cx")) if extent is not None else None,
                int(extent.attrib.get("cy")) if extent is not None else None,
                _nearest_paragraph_id(drawing, paragraph_by_path),
                str(output),
                _position_data(container, "positionH"),
                _position_data(container, "positionV"),
                _wrap_type(container),
            )
        )
    return images


def _extract_text_boxes(
    document_xml: ET.Element, paragraphs: list[ParagraphRecord]
) -> list[TextBoxRecord]:
    tree = document_xml.getroottree()
    paragraph_by_path = {
        tree.getpath(paragraph): record
        for paragraph, record in zip(document_xml.iter(_tag(W_NS, "p")), paragraphs)
    }
    records: list[TextBoxRecord] = []
    for text_box in document_xml.iter(_tag(W_NS, "txbxContent")):
        text = "\n".join(
            "".join(node.text or "" for node in paragraph.iter(_tag(W_NS, "t")))
            for paragraph in text_box.iter(_tag(W_NS, "p"))
        ).strip()
        if not text:
            continue
        container = _nearest_drawing_container(text_box)
        extent = container.find(_tag(WP_NS, "extent")) if container is not None else None
        records.append(
            TextBoxRecord(
                text,
                "floating" if container is not None and container.tag == _tag(WP_NS, "anchor") else "inline",
                int(extent.attrib["cx"]) if extent is not None and "cx" in extent.attrib else None,
                int(extent.attrib["cy"]) if extent is not None and "cy" in extent.attrib else None,
                _position_data(container, "positionH"),
                _position_data(container, "positionV"),
                _nearest_paragraph_id(text_box, paragraph_by_path),
            )
        )
    return records


def _nearest_drawing_container(element: ET.Element) -> ET.Element | None:
    current = element.getparent()
    while current is not None:
        if current.tag in {_tag(WP_NS, "anchor"), _tag(WP_NS, "inline")}:
            return current
        current = current.getparent()
    return None


def _position_data(container: ET.Element | None, kind: str) -> dict[str, Any] | None:
    if container is None:
        return None
    position = container.find(_tag(WP_NS, kind))
    if position is None:
        return None
    alignment = position.find(_tag(WP_NS, "align"))
    offset = position.find(_tag(WP_NS, "posOffset"))
    return {
        "relative_from": position.attrib.get("relativeFrom"),
        "align": alignment.text if alignment is not None else None,
        "offset_emu": int(offset.text) if offset is not None and offset.text else None,
    }


def _wrap_type(container: ET.Element | None) -> str | None:
    if container is None:
        return None
    for child in list(container):
        if child.tag.startswith(f"{{{WP_NS}}}wrap"):
            return child.tag.rsplit("}", 1)[-1]
    return None


def _extract_header_footer_stories(package: zipfile.ZipFile) -> dict[str, list[str]]:
    stories: dict[str, list[str]] = {"headers": [], "footers": []}
    for package_path in package.namelist():
        if not package_path.startswith(("word/header", "word/footer")):
            continue
        if not package_path.endswith(".xml"):
            continue
        root = ET.fromstring(package.read(package_path))
        text = "\n".join(
            "".join(node.text or "" for node in paragraph.iter(_tag(W_NS, "t")))
            for paragraph in root.iter(_tag(W_NS, "p"))
        ).strip()
        if text:
            key = "headers" if "/header" in package_path else "footers"
            stories[key].append(text)
    return stories


def _nearest_paragraph_id(
    element: ET.Element, paragraph_by_path: dict[str, ParagraphRecord]
) -> str | None:
    current = element
    tree = element.getroottree()
    while current is not None:
        if current.tag == _tag(W_NS, "p"):
            record = paragraph_by_path.get(tree.getpath(current))
            return record.node_id if record is not None else None
        current = current.getparent()
    return None


def _apply_replacements(
    document_xml: ET.Element,
    replacements: dict[str, str],
    normalize_body_italic: bool = False,
    bullet_num_id: str | None = None,
) -> None:
    paragraphs = list(document_xml.iter(_tag(W_NS, "p")))
    records = _extract_paragraphs(document_xml)
    for paragraph, record in zip(paragraphs, records):
        replacement = replacements.get(record.node_id)
        if replacement is None:
            continue
        _replace_paragraph_text(
            paragraph, replacement, normalize_body_italic, bullet_num_id
        )


def _replace_paragraph_text(
    paragraph: ET.Element,
    replacement: str,
    normalize_body_italic: bool,
    bullet_num_id: str | None,
    inherited_tab_positions: tuple[str, ...] = (),
) -> None:
    replacement = _clean_replacement_text(replacement)
    _remove_paragraph_tab_leaders(paragraph, inherited_tab_positions)
    if bullet_num_id:
        _assign_standard_bullet(paragraph, bullet_num_id)
    run_elements = [
        run for run in paragraph.iter(_tag(W_NS, "r"))
        if list(run.iter(_tag(W_NS, "t")))
    ]
    if not run_elements:
        raise DocxLayoutError("Paragraph has no writable text node")
    first_run = run_elements[0]
    body_run = next(
        (run for run in run_elements[1:] if not _run_style(run).get("bold")),
        None,
    )
    if _run_style(first_run).get("bold") and body_run is not None:
        first_properties = first_run.find(_tag(W_NS, "rPr"))
        body_properties = body_run.find(_tag(W_NS, "rPr"))
        if first_properties is not None:
            first_run.remove(first_properties)
        if body_properties is not None:
            first_run.insert(0, copy.deepcopy(body_properties))
    for index, run in enumerate(run_elements):
        text_nodes = list(run.iter(_tag(W_NS, "t")))
        if not text_nodes:
            continue
        chunk = replacement if index == 0 else ""
        text_nodes[0].text = chunk
        if chunk[:1].isspace() or chunk[-1:].isspace():
            text_nodes[0].set(_tag(XML_NS, "space"), "preserve")
        for node in text_nodes[1:]:
            node.text = ""
        if normalize_body_italic:
            properties = run.find(_tag(W_NS, "rPr"))
            if properties is not None:
                italic = properties.find(_tag(W_NS, "i"))
                if italic is not None:
                    properties.remove(italic)


def _remove_paragraph_tab_leaders(
    paragraph: ET.Element, inherited_tab_positions: tuple[str, ...] = ()
) -> None:
    for run in paragraph.iter(_tag(W_NS, "r")):
        for tab in list(run.findall(_tag(W_NS, "tab"))):
            run.remove(tab)
    properties = paragraph.find(_tag(W_NS, "pPr"))
    if properties is None:
        return
    tabs = properties.find(_tag(W_NS, "tabs"))
    if tabs is not None:
        properties.remove(tabs)
    if inherited_tab_positions:
        tabs = ET.Element(_tag(W_NS, "tabs"))
        _insert_ppr_child_in_schema_order(properties, tabs)
        for position in inherited_tab_positions:
            clear_tab = ET.SubElement(tabs, _tag(W_NS, "tab"))
            clear_tab.set(_tag(W_NS, "val"), "clear")
            clear_tab.set(_tag(W_NS, "pos"), position)


def _paragraph_style_id(paragraph: ET.Element) -> str:
    properties = paragraph.find(_tag(W_NS, "pPr"))
    style = properties.find(_tag(W_NS, "pStyle")) if properties is not None else None
    return style.get(_tag(W_NS, "val"), "") if style is not None else ""


def _remove_paragraph_section_properties(paragraph: ET.Element) -> None:
    properties = paragraph.find(_tag(W_NS, "pPr"))
    if properties is None:
        return
    section_properties = properties.find(_tag(W_NS, "sectPr"))
    if section_properties is not None:
        properties.remove(section_properties)


def _require_single_document_body(document_xml: ET.Element) -> None:
    bodies = document_xml.findall(_tag(W_NS, "body"))
    if len(bodies) != 1:
        raise DocxLayoutError(
            f"Invalid DOCX document.xml: expected exactly one w:body, found {len(bodies)}"
        )


def _set_paragraph_style(paragraph: ET.Element, style_id: str) -> None:
    properties = paragraph.find(_tag(W_NS, "pPr"))
    if properties is None:
        properties = ET.Element(_tag(W_NS, "pPr"))
        paragraph.insert(0, properties)
    style = properties.find(_tag(W_NS, "pStyle"))
    if style is None:
        style = ET.Element(_tag(W_NS, "pStyle"))
        _insert_ppr_child_in_schema_order(properties, style)
    style.set(_tag(W_NS, "val"), style_id)


def _ensure_tab_free_style(
    styles_xml: ET.Element, source_style_id: str, cache: dict[str, str]
) -> str:
    if source_style_id in cache:
        return cache[source_style_id]
    source = next(
        (
            style for style in styles_xml.findall(_tag(W_NS, "style"))
            if style.get(_tag(W_NS, "styleId")) == source_style_id
        ),
        None,
    )
    if source is None:
        return source_style_id
    clean_style_id = f"{source_style_id}NoTabs"
    clone = copy.deepcopy(source)
    clone.set(_tag(W_NS, "styleId"), clean_style_id)
    name = clone.find(_tag(W_NS, "name"))
    if name is not None:
        name.set(_tag(W_NS, "val"), f"{name.get(_tag(W_NS, 'val'), source_style_id)} No Tabs")
    for tabs in list(clone.iter(_tag(W_NS, "tabs"))):
        parent = tabs.getparent()
        if parent is not None:
            parent.remove(tabs)
    styles_xml.append(clone)
    cache[source_style_id] = clean_style_id
    return clean_style_id


def _extract_style_tab_positions(payload: bytes) -> dict[str, tuple[str, ...]]:
    root = ET.fromstring(payload)
    styles: dict[str, tuple[str | None, tuple[str, ...]]] = {}
    for style in root.findall(_tag(W_NS, "style")):
        style_id = style.get(_tag(W_NS, "styleId"))
        if not style_id:
            continue
        based_on = style.find(_tag(W_NS, "basedOn"))
        tabs = tuple(
            position
            for tab in style.findall("./" + _tag(W_NS, "pPr") + "/" + _tag(W_NS, "tabs") + "/" + _tag(W_NS, "tab"))
            if (position := tab.get(_tag(W_NS, "pos")))
        )
        styles[style_id] = (
            based_on.get(_tag(W_NS, "val")) if based_on is not None else None,
            tabs,
        )

    resolved: dict[str, tuple[str, ...]] = {}

    def resolve(style_id: str, visiting: set[str] | None = None) -> tuple[str, ...]:
        if style_id in resolved:
            return resolved[style_id]
        visiting = visiting or set()
        if style_id in visiting or style_id not in styles:
            return ()
        visiting.add(style_id)
        based_on, own_tabs = styles[style_id]
        base_positions = resolve(based_on, visiting) if based_on else ()
        positions = tuple(dict.fromkeys((*base_positions, *own_tabs)))
        resolved[style_id] = positions
        return positions

    for style_id in styles:
        resolve(style_id)
    return resolved


def _clean_replacement_text(value: str) -> str:
    return LexicalSanitizer.clean_text(value)


def _create_standard_bullet_numbering(payload: bytes) -> tuple[bytes, str]:
    root = ET.fromstring(payload)
    abstract_ids = [int(node.get(_tag(W_NS, "abstractNumId"), "0")) for node in root.findall(_tag(W_NS, "abstractNum"))]
    num_ids = [int(node.get(_tag(W_NS, "numId"), "0")) for node in root.findall(_tag(W_NS, "num"))]
    abstract_id = str(max(abstract_ids, default=0) + 1)
    num_id = str(max(num_ids, default=0) + 1)
    abstract = ET.Element(_tag(W_NS, "abstractNum"))
    abstract.set(_tag(W_NS, "abstractNumId"), abstract_id)
    level = ET.SubElement(abstract, _tag(W_NS, "lvl"))
    level.set(_tag(W_NS, "ilvl"), "0")
    for name, value in (
        ("start", "1"),
        ("numFmt", "bullet"),
        ("lvlText", "•"),
        ("lvlJc", "left"),
        ("suff", "space"),
    ):
        node = ET.SubElement(level, _tag(W_NS, name))
        node.set(_tag(W_NS, "val"), value)
    paragraph_properties = ET.SubElement(level, _tag(W_NS, "pPr"))
    indent = ET.SubElement(paragraph_properties, _tag(W_NS, "ind"))
    indent.set(_tag(W_NS, "left"), "360")
    indent.set(_tag(W_NS, "hanging"), "180")
    run_properties = ET.SubElement(level, _tag(W_NS, "rPr"))
    fonts = ET.SubElement(run_properties, _tag(W_NS, "rFonts"))
    fonts.set(_tag(W_NS, "ascii"), "Arial")
    fonts.set(_tag(W_NS, "hAnsi"), "Arial")
    first_num = root.find(_tag(W_NS, "num"))
    root.insert(root.index(first_num) if first_num is not None else len(root), abstract)
    number = ET.SubElement(root, _tag(W_NS, "num"))
    number.set(_tag(W_NS, "numId"), num_id)
    reference = ET.SubElement(number, _tag(W_NS, "abstractNumId"))
    reference.set(_tag(W_NS, "val"), abstract_id)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), num_id


def _assign_standard_bullet(paragraph: ET.Element, num_id: str) -> None:
    properties = paragraph.find(_tag(W_NS, "pPr"))
    if properties is None:
        properties = ET.Element(_tag(W_NS, "pPr"))
        paragraph.insert(0, properties)
    numbering = properties.find(_tag(W_NS, "numPr"))
    if numbering is not None:
        properties.remove(numbering)
    numbering = ET.Element(_tag(W_NS, "numPr"))
    _insert_ppr_child_in_schema_order(properties, numbering)
    for child in list(numbering):
        numbering.remove(child)
    level = ET.SubElement(numbering, _tag(W_NS, "ilvl"))
    level.set(_tag(W_NS, "val"), "0")
    number = ET.SubElement(numbering, _tag(W_NS, "numId"))
    number.set(_tag(W_NS, "val"), num_id)
    indent = properties.find(_tag(W_NS, "ind"))
    if indent is None:
        indent = ET.Element(_tag(W_NS, "ind"))
        _insert_ppr_child_in_schema_order(properties, indent)
        indent.set(_tag(W_NS, "left"), "360")
        indent.set(_tag(W_NS, "hanging"), "180")


def _insert_ppr_child_in_schema_order(properties: ET.Element, child: ET.Element) -> None:
    order = {name: index for index, name in enumerate(_PPR_CHILD_ORDER)}
    child_rank = order[ET.QName(child).localname]
    insertion_index = next(
        (
            index for index, existing in enumerate(properties)
            if order.get(ET.QName(existing).localname, -1) > child_rank
        ),
        len(properties),
    )
    properties.insert(insertion_index, child)

