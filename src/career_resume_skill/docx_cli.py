from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .docx_engine import convert_docx_to_pdf, inject_docx_text, inspect_docx
from .docx_profile import import_docx_as_master_cv
from .quality import audit_docx_health


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect, audit, inject, and convert DOCX resumes.")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_command = commands.add_parser("inspect", help="Extract DOCX layout and media metadata.")
    inspect_command.add_argument("source", type=Path)
    inspect_command.add_argument("--resources-dir", type=Path)
    inspect_command.add_argument("--manifest", type=Path)

    audit_command = commands.add_parser("audit", help="Check source DOCX layout without a JD or LLM.")
    audit_command.add_argument("source", type=Path)

    inject_command = commands.add_parser("inject", help="Replace paragraph text in-place.")
    inject_command.add_argument("source", type=Path)
    inject_command.add_argument("output", type=Path)
    inject_command.add_argument(
        "--replacements",
        type=Path,
        required=True,
        help="UTF-8 JSON object mapping paragraph node_id to replacement text.",
    )
    inject_command.add_argument(
        "--no-length-budget",
        action="store_true",
        help="Disable the default font-based wrapped-line budget.",
    )

    convert_command = commands.add_parser("convert", help="Convert DOCX to PDF with LibreOffice.")
    convert_command.add_argument("source", type=Path)
    convert_command.add_argument("--output-dir", type=Path)

    master_command = commands.add_parser(
        "to-master-cv", help="Convert a real DOCX resume into Master CV JSON."
    )
    master_command.add_argument("source", type=Path)
    master_command.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    arguments = _parser().parse_args()
    if arguments.command == "inspect":
        report = inspect_docx(arguments.source, arguments.resources_dir)
        if arguments.manifest:
            report.write_manifest(arguments.manifest)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return
    if arguments.command == "audit":
        print(json.dumps(audit_docx_health(arguments.source), ensure_ascii=False, indent=2))
        return
    if arguments.command == "inject":
        replacements = json.loads(arguments.replacements.read_text(encoding="utf-8"))
        if not isinstance(replacements, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in replacements.items()
        ):
            raise TypeError("replacement JSON must be an object of string keys and string values")
        output = inject_docx_text(
            arguments.source,
            arguments.output,
            replacements,
            enforce_length_budget=not arguments.no_length_budget,
        )
        print(output)
        return
    if arguments.command == "to-master-cv":
        result = import_docx_as_master_cv(arguments.source)
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(arguments.output.resolve())
        return
    pdf = convert_docx_to_pdf(arguments.source, arguments.output_dir)
    print(pdf)


if __name__ == "__main__":
    main()
