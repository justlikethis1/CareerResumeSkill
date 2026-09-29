from __future__ import annotations

import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import ImageFont

_FONT_ALIASES = {
    "arial": "arial.ttf",
    "calibri": "calibri.ttf",
    "cambria": "cambria.ttc",
    "times new roman": "times.ttf",
    "courier new": "cour.ttf",
    "liberation sans": "LiberationSans-Regular.ttf",
    "liberation serif": "LiberationSerif-Regular.ttf",
    "dejavu sans": "DejaVuSans.ttf",
    "microsoft yahei": "msyh.ttc",
    "simsun": "simsun.ttc",
    "noto sans cjk sc": "NotoSansCJK-Regular.ttc",
}
_BOLD_FONT_ALIASES = {
    "arial": "arialbd.ttf",
    "calibri": "calibrib.ttf",
    "cambria": "cambriab.ttf",
    "times new roman": "timesbd.ttf",
    "liberation sans": "LiberationSans-Bold.ttf",
    "liberation serif": "LiberationSerif-Bold.ttf",
    "dejavu sans": "DejaVuSans-Bold.ttf",
    "noto sans cjk sc": "NotoSansCJK-Bold.ttc",
}
_LAYOUT_TOKEN_RE = re.compile(
    r"[A-Za-z0-9_#+.-]+|[\u2e80-\u9fff\uf900-\ufaff]|[^\s]"
)
_LINE_START_PROHIBITED = set("，。！？、；：,.!?;:%‰)]}）］｝〕〉》」』】〗〙〛")
_LINE_END_PROHIBITED = set("([{（［｛〔〈《「『【〖〘〚")


@lru_cache(maxsize=64)
def _font(font_name: str, pixel_size: int, bold: bool = False) -> Any:
    requested = font_name.strip() or "Arial"
    candidates: list[Path] = []
    font_roots = (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path("/usr/share/fonts/truetype/msttcorefonts"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/opentype/noto"),
    )
    alias = (
        _BOLD_FONT_ALIASES.get(requested.casefold()) if bold
        else _FONT_ALIASES.get(requested.casefold())
    )
    if alias:
        candidates.extend(root / alias for root in font_roots)
    candidates.extend(
        root / filename
        for root in font_roots
        for filename in (
            f"{requested.replace(' ', '')}.ttf",
            f"{requested.replace(' ', '-')}.ttf",
            "arialbd.ttf" if bold else "arial.ttf",
            "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            try:
                return ImageFont.truetype(str(candidate), pixel_size)
            except OSError:
                continue
    return ImageFont.load_default(size=pixel_size)


def estimate_string_width(text: str, font_name: str, font_size_pt: float, bold: bool = False) -> float:
    """Measure text width in points using the closest locally available font file."""
    pixel_size = max(1, round(font_size_pt * 96 / 72))
    return float(_font(font_name, pixel_size, bold).getlength(text)) * 72 / 96


def resolved_font_path(font_name: str, font_size_pt: float, bold: bool = False) -> str | None:
    pixel_size = max(1, round(font_size_pt * 96 / 72))
    path = getattr(_font(font_name, pixel_size, bold), "path", None)
    return str(path) if path else None


def estimate_wrapped_line_count(
    text: str,
    available_width_pt: float,
    font_name: str,
    font_size_pt: float,
    bold: bool = False,
) -> int:
    return len(measure_wrapped_lines(text, available_width_pt, font_name, font_size_pt, bold))


def measure_wrapped_lines(
    text: str,
    available_width_pt: float,
    font_name: str,
    font_size_pt: float,
    bold: bool = False,
) -> list[float]:
    return [width for width, _ in _wrapped_line_details(
        text, available_width_pt, font_name, font_size_pt, bold
    )]


def _wrapped_line_details(
    text: str,
    available_width_pt: float,
    font_name: str,
    font_size_pt: float,
    bold: bool = False,
) -> list[tuple[float, int]]:
    if not text.strip():
        return []
    if available_width_pt <= 0:
        raise ValueError("available_width_pt must be greater than zero")
    font = _font(font_name, max(1, round(font_size_pt * 96 / 72)), bold)
    lines: list[tuple[float, int]] = []
    line_width = 0.0
    line_units = 0
    line_tokens: list[tuple[str, float, int]] = []
    space_width = float(font.getlength(" ")) * 72 / 96

    def flush_line() -> None:
        nonlocal line_width, line_units, line_tokens
        if line_tokens:
            lines.append((line_width, line_units))
        line_width = 0.0
        line_units = 0
        line_tokens = []

    previous_end = 0
    for match in _LAYOUT_TOKEN_RE.finditer(text):
        token = match.group(0)
        separated = bool(text[previous_end:match.start()])
        previous_end = match.end()
        token_width = float(font.getlength(token)) * 72 / 96
        token_units = 0 if all(unicodedata.category(char).startswith("P") for char in token) else 1
        gap_width = space_width if separated and line_tokens else 0.0

        if line_width + gap_width + token_width > available_width_pt and line_tokens:
            if token in _LINE_START_PROHIBITED:
                line_width += gap_width + token_width
                line_tokens.append((token, token_width, token_units))
                line_units += token_units
                continue
            if line_tokens[-1][0] in _LINE_END_PROHIBITED:
                opening, opening_width, opening_units = line_tokens.pop()
                line_width -= opening_width
                line_units -= opening_units
                flush_line()
                line_tokens.append((opening, opening_width, opening_units))
                line_width = opening_width
                line_units = opening_units
                gap_width = 0.0
            else:
                flush_line()
                gap_width = 0.0

        if token_width <= available_width_pt or len(token) == 1:
            line_width += gap_width + token_width
            line_units += token_units
            line_tokens.append((token, token_width, token_units))
            continue

        if line_tokens:
            flush_line()
        for character in token:
            character_width = float(font.getlength(character)) * 72 / 96
            if line_width and line_width + character_width > available_width_pt:
                flush_line()
            line_width += character_width
            line_units += 1
            line_tokens.append((character, character_width, 1))

    flush_line()
    return lines


def evaluate_bullet_geometry(
    text: str,
    available_width_pt: float,
    font_name: str,
    font_size_pt: float,
    target_lines: int = 2,
    bold: bool = False,
) -> dict[str, Any]:
    details = _wrapped_line_details(text, available_width_pt, font_name, font_size_pt, bold)
    widths = [width for width, _ in details]
    saturation = sum(widths) / (target_lines * available_width_pt)
    last_line_ratio = widths[-1] / available_width_pt if widths else 0.0
    status = (
        "OVERFLOW" if len(widths) > target_lines else
        "UNDERFLOW" if len(widths) < target_lines or last_line_ratio < 0.35 else
        "FIT"
    )
    return {
        "estimated_lines": len(widths),
        "line_widths_pt": [round(width, 2) for width in widths],
        "last_line_ratio": round(last_line_ratio, 4),
        "last_line_words": details[-1][1] if details else 0,
        "orphan_words": len(details) > 1 and details[-1][1] <= 2,
        "saturation_ratio": round(saturation, 4),
        "status": status,
    }