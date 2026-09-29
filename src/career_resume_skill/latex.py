from __future__ import annotations

import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pypdf import PdfReader

from .facts import extract_metrics, normalize_metric
from .quality import _is_primary_metric
from .tools import find_tectonic

_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_ESCAPE_RE = re.compile("|".join(re.escape(char) for char in _ESCAPE_MAP))


def escape_latex(value: Any) -> str:
    return _ESCAPE_RE.sub(lambda match: _ESCAPE_MAP[match.group()], str(value))


def _escape_tree(value: Any) -> Any:
    if isinstance(value, str):
        return escape_latex(value)
    if isinstance(value, dict):
        return {key: _escape_tree(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_escape_tree(child) for child in value]
    return value


def render_template(template_name: str, content: dict[str, Any], output_path: Path, compact: int = 0) -> Path:
    if template_name not in {"resume", "cover_letter"}:
        raise ValueError("template_name must be 'resume' or 'cover_letter'")
    if compact not in {0, 1, 2}:
        raise ValueError("compact must be 0, 1, or 2")
    template_dir = Path(__file__).with_name("templates")
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        autoescape=False,
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<*",
        comment_end_string="*>",
    )
    environment.filters["latex_escape"] = escape_latex
    template = environment.get_template(f"{template_name}.tex.j2")
    safe_content = _escape_tree(content)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template.render(**safe_content, compact=compact), encoding="utf-8")
    return output_path


def find_compiler() -> tuple[str, list[str]]:
    candidates = (
        ("tectonic", ["tectonic", "--keep-logs"]),
        ("xelatex", ["xelatex", "-interaction=nonstopmode", "-halt-on-error"]),
        ("lualatex", ["lualatex", "-interaction=nonstopmode", "-halt-on-error"]),
    )
    for executable, command in candidates:
        if shutil.which(executable):
            return executable, command
    local_executable = find_tectonic()
    if local_executable:
        return local_executable, [local_executable, "--keep-logs"]
    raise RuntimeError(
        "No fontspec-compatible LaTeX compiler found. Install tectonic, xelatex, or lualatex "
        "before requesting PDF output; use compile_documents=false for a .tex-only dry run."
    )


def compile_latex(tex_path: Path, page_limit: int = 1) -> dict[str, Any]:
    compiler, command = find_compiler()
    try:
        process = subprocess.run(
            [*command, tex_path.name],
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "LaTeX compilation exceeded 600 seconds. Tectonic may still be downloading "
            "its first-time bundle; retry after the download has completed."
        ) from error
    log = ((process.stdout or "") + "\n" + (process.stderr or "")).strip()
    pdf_path = tex_path.with_suffix(".pdf")
    if process.returncode != 0 or not pdf_path.exists():
        raise RuntimeError(f"LaTeX compilation failed with {compiler}:\n{log[-6000:]}")
    pages = len(PdfReader(str(pdf_path)).pages)
    if pages > page_limit:
        raise PageLimitError(pages, page_limit, log)
    return {"pdf_path": str(pdf_path.resolve()), "tex_path": str(tex_path.resolve()), "pages": pages, "compiler": compiler, "log": log[-6000:]}


def prune_low_priority_resume(content: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    pruned = deepcopy(content)
    item_scores = pruned.get("strategy", {}).get("item_scores", {})
    candidates: list[tuple[float, int, int, dict[str, Any]]] = []
    for section_index, section in enumerate(pruned.get("sections", [])):
        for item_index, item in enumerate(section.get("items", [])):
            item_id = item.get("source_item_id", "")
            candidates.append(
                (float(item_scores.get(item_id, 0)), section_index, item_index, item)
            )
    bullet_candidates: list[tuple[float, int, dict[str, Any], int]] = []
    for score, _, _, item in candidates:
        bullets = item.get("bullets", [])
        if len(bullets) <= 1:
            continue
        for bullet_index in reversed(range(len(bullets))):
            if not _bullet_has_primary_metric(bullets[bullet_index]):
                bullet_candidates.append((score, -len(bullets), item, bullet_index))
                break
    if bullet_candidates:
        _, _, item, target_index = min(
            bullet_candidates, key=lambda candidate: (candidate[0], candidate[1])
        )
        removed = item["bullets"].pop(target_index)
        if item.get("evidence_ids") and len(item["evidence_ids"]) > target_index:
            item["evidence_ids"].pop(target_index)
        return pruned, f"Removed low-priority bullet from {item.get('source_item_id', 'item')}: {removed}"
    removable_items = [
        candidate
        for candidate in candidates
        if len(pruned["sections"][candidate[1]].get("items", [])) > 1
        and not any(_bullet_has_primary_metric(bullet) for bullet in candidate[3].get("bullets", []))
    ]
    if removable_items:
        _, section_index, item_index, item = min(removable_items, key=lambda candidate: candidate[0])
        pruned["sections"][section_index]["items"].pop(item_index)
        return pruned, f"Removed low-priority item: {item.get('source_item_id', item.get('title', 'item'))}"
    return pruned, None


def _bullet_has_primary_metric(bullet: str) -> bool:
    return any(
        _is_primary_metric(metric)
        for metric in extract_metrics(bullet)
        if normalize_metric(metric)
    )


class PageLimitError(RuntimeError):
    def __init__(self, pages: int, limit: int, log: str) -> None:
        super().__init__(f"Rendered PDF has {pages} pages; limit is {limit}")
        self.pages = pages
        self.limit = limit
        self.log = log

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": type(self).__name__,
            "message": str(self),
            "pages": self.pages,
            "limit": self.limit,
            "log": self.log,
        }
