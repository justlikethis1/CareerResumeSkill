from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def slug(value: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return cleaned or "Document"


def create_run_directory(output_root: str | Path, candidate: str, company: str) -> tuple[str, Path]:
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    run_dir = Path(output_root).expanduser().resolve() / (
        f"{run_id}_{slug(candidate)}_{slug(company)}"
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_id, run_dir
