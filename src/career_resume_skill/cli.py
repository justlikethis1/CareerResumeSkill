from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a JD-tailored resume and cover-letter application package."
    )
    parser.add_argument("--track", choices=("latex", "docx"), default="latex")
    jd_group = parser.add_mutually_exclusive_group(required=False)
    jd_group.add_argument("--jd", help="Inline JD text or a public HTTP(S) URL.")
    jd_group.add_argument("--jd-file", type=Path, help="UTF-8 text file containing the JD.")
    parser.add_argument("--cv", type=Path, required=False, help="Master CV JSON file.")
    parser.add_argument("--docx-template", type=Path, help="Source DOCX resume for the DOCX track.")
    parser.add_argument("--output-docx", type=Path, help="Destination DOCX path for the DOCX track.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Stable delivery directory for reports and generated LaTeX runs; overrides CAREER_SKILL_OUTPUT_DIR.",
    )
    parser.add_argument("--company", required=False, help="Target company or lab name.")
    parser.add_argument("--tone", default="professional and concise")
    parser.add_argument("--company-context-file", type=Path)
    parser.add_argument("--resume-language", choices=("en", "zh_CN"), default="en")
    parser.add_argument("--date", default="", dest="application_date")
    parser.add_argument("--page-limit", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="Skip LaTeX compilation.")
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Path for the structured result JSON.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Report environment readiness without JD or Master CV inputs.",
    )
    parser.add_argument(
        "--pretty-doctor",
        action="store_true",
        help="Pretty-print --doctor JSON instead of emitting one line.",
    )
    return parser


def _read_inputs(arguments: argparse.Namespace) -> tuple[str, dict[str, Any] | None, str]:
    jd_source = arguments.jd
    if arguments.jd_file:
        jd_source = arguments.jd_file.read_text(encoding="utf-8")
    master_cv = None
    if arguments.track == "latex":
        master_cv = json.loads(arguments.cv.read_text(encoding="utf-8"))
        if not isinstance(master_cv, dict):
            raise TypeError("Master CV JSON must contain an object at the top level")
    company_context = ""
    if arguments.company_context_file:
        company_context = arguments.company_context_file.read_text(encoding="utf-8")
    return jd_source, master_cv, company_context


async def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    from .application import ApplicationService
    from .config import Settings

    jd_source, master_cv, company_context = _read_inputs(arguments)
    settings = Settings.from_env()
    if arguments.output_dir:
        settings = replace(
            settings,
            output_dir=str(arguments.output_dir.expanduser().resolve()),
        )
    service = ApplicationService(settings)
    if arguments.track == "docx":
        output_docx = arguments.output_docx
        if arguments.output_dir and output_docx and not output_docx.is_absolute():
            output_docx = Path(settings.output_dir) / output_docx
        return await service.generate_docx_application_package(
            docx_source=str(arguments.docx_template),
            jd_text=jd_source,
            output_docx=str(output_docx),
            company_name=arguments.company,
            tone=arguments.tone,
            verified_company_context=company_context,
            resume_language=arguments.resume_language,
            application_date=arguments.application_date,
        )
    assert master_cv is not None
    return await service.generate_application_package(
        jd_text=jd_source,
        master_cv_json=master_cv,
        company_name=arguments.company,
        tone=arguments.tone,
        verified_company_context=company_context,
        application_date=arguments.application_date,
        page_limit=arguments.page_limit,
        compile_documents=not arguments.dry_run,
    )


def main() -> None:
    arguments = _parser().parse_args()
    if arguments.doctor:
        from .application import ApplicationService
        from .config import Settings

        try:
            settings = Settings.from_env()
            if arguments.output_dir:
                settings = replace(
                    settings,
                    output_dir=str(arguments.output_dir.expanduser().resolve()),
                )
            print(
                json.dumps(
                    ApplicationService(settings).check_environment(),
                    ensure_ascii=False,
                    indent=2 if arguments.pretty_doctor else None,
                    separators=None if arguments.pretty_doctor else (",", ":"),
                ),
                flush=True,
            )
        except BrokenPipeError:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        return
    if not arguments.jd and not arguments.jd_file:
        _parser().error("one of --jd or --jd-file is required unless --doctor is used")
    if not arguments.company:
        _parser().error("--company is required unless --doctor is used")
    if arguments.track == "docx":
        if not arguments.docx_template or not arguments.output_docx:
            _parser().error("--docx-template and --output-docx are required for --track docx")
        if arguments.cv:
            _parser().error("--cv is only used with --track latex")
    elif not arguments.cv:
        _parser().error("--cv is required for --track latex")
    result = asyncio.run(_run(arguments))
    if arguments.report:
        report_path = arguments.report.expanduser().resolve()
    else:
        output_root = arguments.output_dir.expanduser().resolve() if arguments.output_dir else Path(
            os.getenv("CAREER_SKILL_OUTPUT_DIR", "output")
        ).expanduser().resolve()
        report_path = output_root / "application_package.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report_path)


if __name__ == "__main__":
    main()
