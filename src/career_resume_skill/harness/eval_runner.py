from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .assertions import EvalHarnessReport, GoldenTestCase, evaluate_report


def evaluate_report_file(
    report_path: str | Path,
    *,
    case: GoldenTestCase | None = None,
) -> EvalHarnessReport:
    path = Path(report_path).expanduser().resolve()
    report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return evaluate_report(report, case or GoldenTestCase(id=path.parent.name))


def load_cases(path: str | Path) -> dict[str, GoldenTestCase]:
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    values = payload if isinstance(payload, list) else payload.get("cases", [payload])
    cases = [GoldenTestCase.model_validate(value) for value in values]
    return {case.id: case for case in cases}


def write_scorecard(results: list[EvalHarnessReport], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Application Evaluation Scorecard", "", "| Case | Passed | Pages | Metrics | ATS | Issues |", "| --- | --- | ---: | ---: | ---: | --- |"]
    for result in results:
        lines.append(
            f"| {result.test_case_id} | {result.passed} | "
            f"{result.page_count if result.page_count is not None else 'n/a'} | "
            f"{result.metric_retention_rate:.2f} | "
            f"{result.ats_score if result.ats_score is not None else 'n/a'} | "
            f"{', '.join(result.issues) or 'none'} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path