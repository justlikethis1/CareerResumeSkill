from __future__ import annotations

import importlib.metadata
import os
import shutil
from pathlib import Path
from typing import Any

from .config import Settings


def find_libreoffice() -> str | None:
    configured = os.getenv("LIBREOFFICE_PATH", "").strip()
    candidates = [
        str(Path(configured).expanduser()) if configured else None,
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        str(Path.home() / "AppData/Local/Programs/LibreOffice/program/soffice.exe"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def find_tectonic() -> str | None:
    configured = os.getenv("TECTONIC_PATH", "").strip()
    candidates = [
        str(Path(configured).expanduser()) if configured else None,
        shutil.which("tectonic"),
        shutil.which("tectonic.exe"),
        str(Path.cwd() / ".tools/tectonic/tectonic.exe"),
        str(Path(__file__).parents[2] / ".tools/tectonic/tectonic.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def find_microsoft_word() -> str | None:
    configured = os.getenv("MICROSOFT_WORD_PATH", "").strip()
    candidates = [
        str(Path(configured).expanduser()) if configured else None,
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def environment_report(settings: Settings | None = None) -> dict[str, Any]:
    active = settings or Settings.from_env()
    output_dir = Path(active.output_dir).expanduser().resolve()
    dependencies: dict[str, str | None] = {}
    for package in ("pydantic", "mcp", "python-docx", "pypdf", "httpx", "jinja2"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = None
    return {
        "api": {
            "deepseek_configured": active.has_api_key,
            "base_url": active.base_url,
            "model": active.model,
        },
        "compilers": {
            "tectonic": find_tectonic(),
            "libreoffice": find_libreoffice(),
            "microsoft_word": find_microsoft_word(),
        },
        "dependencies": dependencies,
        "output": {
            "directory": str(output_dir),
            "exists": output_dir.is_dir(),
            "writable": _is_writable(output_dir),
        },
    }


def _is_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".career-resume-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False
