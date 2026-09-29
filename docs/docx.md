# DOCX Layout Cloning and In-situ Injection

## What this module guarantees

The engine opens a `.docx` as an OOXML ZIP package and preserves entries it does not need to change. Text replacement writes the entire new text into the first writable run and clears later runs' text, retaining their `rPr`. It removes explicit tabs/leaders while preserving the replaced paragraph's style and alignment. Bullet-group injection may also clone/remove paragraphs or update numbering XML; unmodified media and relationships are copied unchanged.

This is the correct strategy for high visual fidelity. Rebuilding a Word document from a new `python-docx` document would lose unsupported layout details such as floating shapes, custom XML, and some drawing properties.

## Three MCP tools

### `inspect_docx_layout`

Input:

```json
{
  "source_path": "F:/Resume/master.docx",
  "resources_dir": "F:/Resume/resources",
  "manifest_path": "F:/Resume/layout.json"
}
```

`resources_dir` and `manifest_path` are optional. The result contains:

- `paragraphs[].node_id`: stable replacement key for the current document
- `paragraphs[].runs[].style`: font family, size, color, bold, italic, and character spacing
- `paragraphs[].style`: paragraph style, alignment, before/after spacing, and line spacing
- `paragraphs[].table_path`: location inside a table cell
- `layout`: column count, page size, and margins
- `layout.sections[]`: page size, margins, and column count for every section, not only the first section
- `layout.styles`: `styles.xml` catalog with style type, display name, `based_on` inheritance, paragraph properties, and run properties
- `layout.stories`: text extracted from headers and footers
- `images[]`: relationship ID, package target, inline/floating anchor, EMU dimensions, extracted image path, horizontal/vertical relative position, and wrap type
- `text_boxes[]`: text-box content, inline/floating anchor, EMU dimensions, position offsets, and containing paragraph ID

Direct paragraph/run properties and the style catalog are reported separately. This preserves the distinction between a value explicitly set on a node and a value inherited from Word's style hierarchy; consumers can resolve `style_id -> based_on` without losing the original evidence.

Always inspect first. Node IDs are document-specific and must not be guessed or reused across different source files.

### `inject_docx_layout`

Input:

```json
{
  "source_path": "F:/Resume/master.docx",
  "output_path": "F:/Resume/output/tailored.docx",
  "replacements": {
    "p:3:body": "Quantitative developer with Python and C++ experience"
  },
  "enforce_length_budget": true
}
```

By default, source font metrics and the available page/table-cell width estimate wrapped lines. Replacement lines must not exceed the greater of two lines and the original line count. This is an approximate layout guard, not a truthfulness check or an exact Word renderer.

Unknown node IDs, paragraphs without writable text nodes, and over-budget replacements fail explicitly. Set `enforce_length_budget=false` only after reviewing the rendered document.

The source and output paths must differ. The engine writes a temporary ZIP beside the requested output and atomically replaces the destination only after the package is complete, so an interrupted replacement does not leave a partially written DOCX at the final path.

## End-to-end DOCX application package

`generate_docx_application_package` is the template-preserving route. It imports the real DOCX into a conservative Master CV, calls the JD/DeepSeek tailoring flow, maps generated bullets back to existing source paragraph IDs, injects them into the original DOCX, converts it to PDF, and generates a separate JD-targeted Cover Letter PDF, paste-ready TXT, and Markdown file. The result returns the text and Markdown paths as `cover_letter_text_path` and `cover_letter_md_path`. The Resume never switches to the built-in LaTeX Resume template; the Cover Letter uses the controlled LaTeX letter template.

The result includes `replacement_count` and `skipped_replacements`. The original-template route does not apply a fixed character gate to content bullets; it preserves the paragraph/run structure and reports the exact replacement mapping. Title and metadata paragraphs are never synthesized as new nodes.

Every end-to-end DOCX package also returns `quality_report`. It compares the source/output DOCX text and source/output PDF extraction separately: page count, private-use bullet characters, non-breaking/soft hyphens, `hyphen + space + hyphen` patterns, and duplicate non-empty lines. A PDF-only delta with no DOCX delta indicates a LibreOffice/font text-extraction artifact rather than an XML injection defect.

### `convert_docx_to_pdf`

Input:

```json
{
  "docx_path": "F:/Resume/output/tailored.docx",
  "output_dir": "F:/Resume/output/pdf"
}
```

This calls `soffice --headless --convert-to pdf`. Install LibreOffice separately and ensure `soffice` or `libreoffice` is on PATH. The module does not silently fall back to a re-created document or a screenshot renderer.

## Python API

```python
from career_resume_skill.docx_engine import inject_docx_text, inspect_docx

report = inspect_docx("master.docx", "resources")
paragraph = next(item for item in report.paragraphs if "Python" in item.text)
inject_docx_text(
    "master.docx",
    "tailored.docx",
    {paragraph.node_id: "Python engineer with verified ML systems experience"},
)
```

For production runs, save `report.write_manifest(...)` beside the generated document so the input layout and replacement mapping are auditable.

## CLI

The same engine is available without MCP:

```powershell
career-resume-docx inspect master.docx --manifest output/layout.json
career-resume-docx audit master.docx
career-resume-docx inject master.docx output/tailored.docx --replacements output/replacements.json
career-resume-docx convert output/tailored.docx --output-dir output/pdf
```

`replacements.json` must be a JSON object whose keys are `paragraphs[].node_id` values returned by `inspect`. Use `--no-length-budget` only after reviewing the rendered result.

## Current boundary

The engine intentionally works at paragraph level. It does not infer semantic sections from arbitrary visual placement, does not rewrite text inside charts or SmartArt, and does not guarantee that a replacement with `enforce_length_budget=false` remains one page. Those cases require human review after PDF conversion.
