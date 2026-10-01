# CareerResumeSkill Final Delivery Summary

## Scope
This package prepares evidence-grounded tailored resumes and cover letters for AI, research, systems, operations, and cross-industry roles while preserving strict verification gates.

## Output Location

Use `--output-dir <directory>` to pin a run's generated reports and LaTeX artifacts to a stable delivery directory. Without the flag, the CLI reads `CAREER_SKILL_OUTPUT_DIR` from `.env` and defaults to `F:\CareerResumeSkill\output`. DOCX output is controlled by `--output-docx`; a relative DOCX path is placed under `--output-dir` when that flag is supplied. Each LaTeX package still receives its own timestamped run directory to prevent overwrites.

## Core capabilities
- Resume tailoring from Master CV + JD
- Evidence-aware bullet budgeting and compression
- Section regrouping by source item provenance
- Cover Letter generation with hook-first opening and evidence-based trade-off reasoning
- Truthfulness checks for unsupported terms and invalid metric claims
- DOCX and PDF export pipeline with typography and integrity validation
- Ledger entry and application report generation

## Key quality constraints
- No unverified technical claims
- No unsupported résumé skill injection
- No trailing dash or broken tab-leader artifacts in PDF output
- No section mismatch after hydration
- Cross-industry role detection for technical and non-technical hiring contexts

## Verification status
The current codebase is verified by the project test suite:
- `pytest -q`: 243 passed
- `ruff check src/career_resume_skill tests`: all checks passed

## Component Coverage
The final verification covers the public application paths and their major internal stages:

| Area | Coverage | Result |
| --- | --- | --- |
| Environment | API configuration, Python dependencies, Tectonic, LibreOffice, Word, output permissions | Passed |
| Evidence and analysis | JD classification, ATS extraction, gap analysis, evidence IDs, metric and technology provenance | Passed |
| LLM contracts | JSON schema validation, repair guidance, resume tailoring, cover-letter drafting, company-claim policy | Passed |
| Resume quality | Primary-metric restoration, truthfulness, skill subset, duplicate bullets, blacklist and punctuation gates | Passed |
| LaTeX track | Resume rendering, cover-letter rendering, page budget, metric-protected overflow pruning, PDF extraction | Passed |
| DOCX track | DOCX ingestion, layout budget, in-situ injection, compact fallback, LibreOffice PDF conversion, final integrity | Passed |
| Delivery artifacts | TXT/Markdown cover letter, PDF/DOCX outputs, application report, verified ledger entry | Passed |

## Latest Live API Verification
Date: 2026-09-29. Both public application-package routes were executed with the configured DeepSeek client and fresh JD inputs.

| Route | Report | Verified | Resume / Cover pages | Cover words | Missing metrics | Unauthorized technologies | Artifacts | Ledger |
| --- | --- | --- | --- | ---: | --- | --- | --- | --- |
| LaTeX | `output/user-test/live-final-latex/application-report.json` | `true` | 1 / 1 | 252 | none | none | all present | written |
| DOCX in-situ | `output/user-test/live-final-docx/application-report.json` | `true` | 1 / 1 | 255 | none | none | all present | written |

The run also exercised the environment doctor, full pytest suite, Ruff, JD analysis, evidence mapping, metric restoration, cover-letter generation, PDF compilation, DOCX injection, PDF extraction, integrity gates, and application ledger. The ledger currently contains 15 entries. No safety gate was relaxed.

## Optimization Follow-up

The follow-up review identified three quality risks and they are now covered by code and regression tests:

- AI systems targets give verified LLM/post-training/RLHF/DPO evidence a deterministic Tier 1/Tier 2 budget floor.
- DOCX section headings receive a bounded minimum paragraph separation while retaining distinct OOXML paragraph nodes.
- Evidence-supported exact JD phrases are passed explicitly to cover-letter generation; singular/plural pipeline and workflow variants are transparent ATS aliases.

The optimized live DOCX report is `output/user-test/live-optimization-docx-v4/application-report.json`. It passed final integrity, preserved all primary metrics, placed the AI Algorithm Intern evidence at Tier 2, emitted the requested exact phrases, and produced no `PROJECT EXPERIENCEFinance_Helper` paragraph adhesion.

## Latest Complete API Re-run

Date: 2026-09-29. Fresh isolated outputs were generated after the review-driven hardening:

- LaTeX: `output/final-api-latex/application-report.json` — `verified=true`, Resume/Cover Letter pages `1/1`, all artifacts present, and Ledger written.
- DOCX in-situ: `output/final-api-docx/application-report.json` and retry `output/final-api-docx-retry/application-report.json` — both correctly returned `verified=false` because the final Resume remained 2 pages after level 0/1/2 layout recovery and targeted re-ranking.
- The DOCX failures passed metric, technology, blacklist, punctuation, glyph, and text Critic checks; only the one-page hard gate failed, so no invalid Ledger entry was written.
- The DOCX two-page result is a correct safety-preserving block, not an uncaught exception or evidence-integrity regression. ATS gaps remain explicit and are never fabricated.

## Review-Driven Hardening

- LaTeX overflow pruning now removes the last non-metric bullet within an item instead of assuming the item tail is removable.
- HTML JD ingestion now honors HTTP charset, HTML meta charset, UTF-8, GB18030, and Big5 fallbacks.
- LLM JSON repair uses a bounded sliding context and retries empty/runtime/API failures without accumulating the full failed history.
- DOCX import recognizes common Chinese role titles, and owned image-extraction resources support explicit cleanup/context-manager use.
- Ledger and private Master CV history updates use OS-held cross-process locks plus atomic JSON replacement; same-role historical reminders share the lock, and macOS LibreOffice discovery is supported.
- Cover Letter word-budget rules now live with the Pydantic model; metric units are declared separately and composed into the extractor regex; ATS handles selected phrase-level singular/plural variants without external stemming dependencies.
- Independent LaTeX Resume/Cover Letter compilation and Cover Letter TXT/Markdown writes now run concurrently; DOCX source-baseline conversion and Cover Letter compilation also run concurrently. Geometry refinement remains sequential because patches share one mutable resume and require revalidation after each change.
- Optional `LIBREOFFICE_PATH`, `TECTONIC_PATH`, and `MICROSOFT_WORD_PATH` overrides support custom compiler installations; `PageLimitError.to_dict()` exposes machine-readable page/limit/log context.
- LLM schema-repair attempts now lower temperature/top-p within bounded floors; same-role, low-score Ledger gaps are supplied only as evidence-gated review reminders, never as candidate facts.
- ATS package scoring now includes Resume and Cover Letter text while retaining a nested `resume_only` score and missing-keyword breakdown, so Cover Letter matches do not hide Resume-specific gaps.
- October 1 live API verification: DOCX and LaTeX DeepSeek routes both produced one-page Resume/Cover Letter PDFs with `verified=true`; Integrity, content Critics, and independent Harness checks passed. The DOCX API package scored 31/31 (package/Resume-only ATS); the LaTeX synthetic-CV package scored 61/53. Follow-up fixes made the cover-letter total floor equal the sum of paragraph hard minima and included source-provided GitHub/LinkedIn links in PDF technology provenance; unsupported technologies remain blocked.
- Phase 2 now includes deterministic `critic/` modules for Cover Letter grammar/repetition and DOCX bullet filler diagnostics.
- Text-content review now also checks duplicate Resume bullets, Markdown prefixes, abnormal whitespace, sentence endings, Cover Letter boilerplate, and paragraph structure.
- `docx_sanitizer.py` centralizes lexical and OOXML sanitization; Harness typography checks hard-fail extraction-visible trailing dash artifacts.
- PDF sanitization now handles grouped and per-glyph `TJ` dash encodings without re-adding pages to a cloned `PdfWriter`; regression coverage verifies page count remains unchanged.
- Phase 3 now includes an offline `harness/` package with report assertions and `python -m career_resume_skill.harness` scorecard generation.
- Phase 1 Pipeline 拆分已取消；系统继续使用 `ApplicationService` 作为唯一用例编排层，MCP/CLI 公共接口保持不变。

The latest consolidated Harness scorecard is `output/user-test/harness-scorecard-content-v1.md`; it reads the real generated PDF text when available, requires page/integrity results, includes expanded text-content Critic results, and both real LaTeX and DOCX reports passed with one page and full metric retention.

## Latest Content/Budget Optimization Run

The optimized DOCX retry is `output/final-api-docx-optimized-retry/application-report.json`. It restored the AI Algorithm Intern evidence to `tier_1` with 3 bullets and recovered the ATS score to `87`; `PyTorch` remains an explicit evidence gap. The run still returned `verified=false` because the retained evidence and template layout produced 2 pages, so the one-page gate correctly blocked Ledger entry. No unsupported technology or metric was added.

The latest optimized DOCX report is `output/final-api-docx-optimized-v3/application-report.json`. It passed the single-page gate with `verified=true`; the PDF contains one page and no exact duplicate page. The ATS score in this stochastic run was `72`, with `PyTorch` and `reliable inference pipelines` reported as explicit gaps rather than fabricated.

The newest complete fixed-directory API run is `output/deliveries/api-run-20260929-final`. The LaTeX retry and DOCX report both passed `verified=true`, produced one-page Resume/Cover Letter artifacts, passed Critic and integrity checks, and wrote Ledger entries. An initial LaTeX attempt was correctly rejected for unsupported per-item technology projection before the compliant retry succeeded.

The latest complete API run is `output/deliveries/api-run-20260929-final-v2`. The first LaTeX attempt was correctly rejected for a missing source-item Evidence ID; its retry and the DOCX route both passed `verified=true`, produced one-page Resume/Cover Letter artifacts, passed Harness/Critic/integrity checks, and wrote Ledger entries.

The sanitizer architecture validation is `output/deliveries/api-run-20260929-sanitizer-v1`. The final LaTeX retry and DOCX retry both passed `verified=true`, produced one-page Resume/Cover Letter artifacts, passed all content/DOCX/Typography Critics, contained no extraction-visible trailing dash lines, and wrote Ledger entries. Earlier attempts correctly demonstrated technology, metric, and repetition safety rejections.

The latest PDF dash-sanitizer verification is `output/deliveries/api-run-20260929-dashfix-v2/application-report.json`: the DOCX route produced exactly one PDF page, raw extracted text contained zero trailing dash lines, Critic/integrity checks passed, and the delivery was recorded in Ledger.

The latest full phase-three API run is `output/deliveries/api-run-20260929-phase3-v1`. Both LaTeX and DOCX routes passed with one-page Resume/Cover Letter artifacts, all integrity and content Critic checks passed, raw PDF text contained no trailing dash artifacts, the Harness scorecard passed, and both Ledger entries were written.

Latest full component run: `output/deliveries/api-run-20260929-final-v4`. Environment, 217 tests, and Ruff passed. The DOCX route and Harness passed with one page, zero raw PDF trailing-dash lines, all integrity/Critic checks green, and a Ledger entry. Three LaTeX attempts were safely rejected for unsupported source-item technologies or Cover Letter evidence/blacklist violations; no safety checks were relaxed.

## Latest Fixed-Directory API Run

The October 1 complete API validation is stored in separate ignored output directories:

- `output/api-full-20261001-docx-retry/application_package.json`: `verified=true`, Resume/Cover Letter `1/1`, Integrity/Critics/Harness passed; Ledger written.
- `output/api-full-20261001-latex-final/application_package.json`: `verified=true`, Resume/Cover Letter `1/1`, Integrity/Critics/Harness passed; Ledger written.
- `pytest -q`: 243 passed; Ruff and `git diff --check` passed.

## Live API outcome expectation
The system should produce a single-page tailored resume, a single-page cover letter PDF, an application report, and a valid DOCX export with ledger metadata when the model output satisfies all evidence gates.

## Notes
- The live API remains sensitive to stochastic model output; if the model emits unsupported terms or misses primary metrics, the system intentionally rejects the output rather than relaxing the evidence gates.
- Recognized primary metrics are restored from the selected source item before rendering, and LaTeX overflow pruning protects metric-bearing bullets. This lowers stochastic failure rate while preserving the final integrity gate.
- This is intentional to preserve truthfulness and document quality.
