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
- `pytest -q`: 258 passed
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
- DOCX PDF conversion remains Word-first; Word COM failures/timeouts are bounded to 60 seconds by default and automatically fall back to LibreOffice after removing partial PDFs. The timeout is configurable within 1-180 seconds.
- DOCX Master CV import remains the dependency boundary; after import, JD analysis and local layout-budget measurement run concurrently because they consume the same source independently. Tailoring still waits for both results, preserving budget and evidence semantics.
- October 1 end-to-end timing samples: DOCX 67.33s and LaTeX 15.76s. These used different inputs/routes and are directional, not a controlled apples-to-apples benchmark. New reports now include `performance.total_seconds` and fixed-name `performance.stages_seconds` fields for the next controlled comparison.
- Application results include privacy-safe `performance.total_seconds` and stage durations under `performance.stages_seconds`; timings contain no JD, resume, API key, or model response text.
- Cover Letter word-budget rules now live with the Pydantic model; metric units are declared separately and composed into the extractor regex; ATS handles selected phrase-level singular/plural variants without external stemming dependencies.
- Independent LaTeX Resume/Cover Letter compilation and Cover Letter TXT/Markdown writes run concurrently; in the DOCX route, source-baseline conversion overlaps evidence-bound Cover Letter generation, then its PDF compilation runs after the draft is ready. Geometry refinement remains sequential because patches share one mutable resume and require revalidation after each change.
- Optional `LIBREOFFICE_PATH`, `TECTONIC_PATH`, and `MICROSOFT_WORD_PATH` overrides support custom compiler installations; `PageLimitError.to_dict()` exposes machine-readable page/limit/log context.
- LLM schema-repair attempts now lower temperature/top-p within bounded floors; same-role, low-score Ledger gaps are supplied only as evidence-gated review reminders, never as candidate facts.
- ATS package scoring now includes Resume and Cover Letter text while retaining a nested `resume_only` score and missing-keyword breakdown, so Cover Letter matches do not hide Resume-specific gaps.
- October 1 live API verification: DOCX and LaTeX DeepSeek routes both produced one-page Resume/Cover Letter PDFs with `verified=true`; Integrity, content Critics, and independent Harness checks passed. The DOCX API package scored 31/31 (package/Resume-only ATS); the LaTeX synthetic-CV package scored 61/53. Follow-up fixes made the cover-letter total floor equal the sum of paragraph hard minima and included source-provided GitHub/LinkedIn links in PDF technology provenance; unsupported technologies remain blocked.
- October 1 performance retest: LaTeX completed in 17.48s with one-page artifacts, `verified=true`, and Harness passing. DOCX took 89.70s and was blocked before package/report creation by a cross-paragraph repetition Critic; no verified Ledger entry was written. The prompt now separates hook and technical-story responsibilities and gives the bounded rewrite a distinct-evidence instruction; this prompt change was not re-tested against the live API because the authorized API run was exhausted.
- Latest authorized perf5 API run: LaTeX completed in 22.32s and passed one-page Integrity/Critic/Harness gates. DOCX stopped after 16.09s during skill-subset validation because the model proposed skills absent from the Master CV; the new post-processing filters those labels into `evidence_gaps` rather than aborting. The October 2 DOCX retry then passed all gates in 71.13s; the model emitted no unsupported extra skills on that stochastic run.
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
- October 2 perf7 API comparison (same DOCX source, JD, company and date as perf6): `fast` DOCX completed in 52.58s wall time versus 67.53s for the retained `baseline` run, with one level-2 candidate PDF export instead of three. Both verified Resume/Cover Letter as 1/1 pages with Integrity, Critics, Ledger, and independent Harness passing. The LaTeX regression completed in 22.89s, also 1/1 pages with all gates and Harness passing; model-generated ATS scores vary between runs. The default DOCX mode is now `fast`, while `layout_strategy="baseline"` and CLI `--docx-layout-strategy baseline` retain the original ascending layout algorithm. Final offline regression: `pytest -q` 258 passed; Ruff on `src tests` and `git diff --check` passed. No further API calls were made after perf7.
- October 2 perf8 API comparison (same inputs as perf7): overlapping the DOCX Cover Letter draft with the first resume PDF conversion reduced DOCX wall time from 52.58s to 38.71s (internal time 51.093s to 37.294s). Both PDF documents remained one page, ATS 31/31, with Integrity, Critics, Ledger, and Harness passing. The LaTeX regression completed in 15.43s with one-page documents and the same gates passing; its different model-generated ATS score is not evidence of a deterministic code change. DOCX `baseline` remains callable; the optimized `fast` mode remains default. Before perf8, the offline suite passed 260 tests, with Ruff on `src tests` and `git diff --check` passing; no additional API requests were made after perf8.
- October 2 perf9 live cycle: same-input DOCX completed in 27.74s wall time (26.314s internal), versus 38.71s (37.294s internal) for perf8; source-baseline conversion overlapped analysis and tailoring, leaving 0.259s of post-tailoring wait. Resume/Cover Letter PDFs were 1/1 pages, ATS 31/31, Integrity/Critics/Ledger/Harness all passed. A distinct synthetic finance-operations CV (`examples/finance_operations_cv.synthetic.json`) and JD exercised LaTeX generalization but stopped after 7.34s before report creation: truthfulness validation reported an unsupported `2`, but no model response was retained to establish whether it was prose or an evidence ID. Later offline repro showed `bullet:2` alone could produce this error. Before perf9, `pytest -q` passed 265 tests with Ruff on `src tests` and `git diff --check` passing.
- October 2 perf10 live cycle: the identical synthetic finance-operations LaTeX route stopped after 12.16s before report creation; truthfulness reported unsupported `2` after two rewrites, but retained logs cannot distinguish prose from evidence-ID contamination. The same-input DOCX route completed in 37.38s (35.933s internal), with one-page Resume/Cover Letter PDFs, ATS 31/31, all Integrity/Critic/Harness checks passing and Ledger written. Versus perf9's 27.74s, this sample was slower primarily in model-facing tailoring (14.383s versus 5.961s); it is not evidence of a PDF performance regression. After the authorized cycle, offline-only repairs restored source-backed profile/bullets when a model persists in inventing a number, made metric restoration append within item budget instead of overwriting another fact, and protected explicit invoice/case counts from LaTeX pruning. A full synthetic finance PDF route and focused boundary tests passed offline; **no post-repair live API success was established**.
- DOCX heading alignment offline follow-up: preserve explicit right-aligned company/location tabs and convert dedicated long-space separators to tabs, while continuing to strip trailing body tabs and leader artifacts. A real DOCX/PDF export from the supplied template placed all four location starts at x=465pt, separated from company names starting at x=54pt; the previously verified bullet payload remained one page. A source title glued to a month-year date is no longer falsely flagged missing when its PDF renders a separating space. Full offline regression: 278 passed, Ruff and `git diff --check` passed; no API calls were made for this layout change.
- Adaptive location and Cover Letter formatting offline follow-up: company/location DOCX headings retain a 12pt minimum separation or move long locations to a new right-aligned line; short and long locations share the same PDF right edge. LaTeX resume headings use independent left/right wrapping columns, and Cover Letters no longer automatically hyphenate English words across lines. Real PDF tests passed for varying location lengths and for one-page Cover Letters; full offline regression passed 281 tests, with Ruff and `git diff --check` clean. No API calls were made for these formatting changes.
- October 2 perf11 authorized cycle: the same finance LaTeX route stopped after 12.93s with unsupported `2` before report/PDF creation; a minimal offline repro then showed an evidence ID ending in `bullet:2` alone triggers the same failure. The same-input real DOCX route stopped after 33.95s when both Cover Letter drafts retained an unsupported `64`; neither live route produced a verified package or Ledger entry. Post-cycle offline-only fixes exclude identifier fields (not prose or numeric DTO fields) from truthfulness scanning and allow one auditable sentence-level Cover Letter fallback only when no verified metric is removed and word bands/Critic/provenance pass. Full offline regression: 289 passed; Ruff and `git diff --check` passed. No API calls were made after the post-cycle fixes, and neither fix has live success verification.
- Targeted perf11 follow-up (offline only): the Cover Letter model request now supplies source numeric values indexed by evidence ID and explicitly forbids calculating experience durations from dates or copying JD-only metrics. A finance fixture test verifies 120 and 8% are provided with their actual citations, while `bullet:2` and unsupported 64 are not offered as claims. The strict postgeneration gates and two-draft limit are unchanged. Full offline regression: 290 passed; Ruff and `git diff --check` passed. No API calls were made; real end-to-end effectiveness remains unverified.
- October 2 perf12 authorized validation: after a 291-test offline pass, the **first** API call repeated the previously blocked synthetic finance CV/JD and completed in 21.21s wall time (19.704s internal). The package returned `verified=true`, Resume/Cover Letter 1/1 pages, ATS 33/31, all Integrity/Content Critics and independent seven-check Harness passed, and Ledger was written. Extracted PDFs retained source 120 invoices and 8% while excluding unsupported SAP and derived "2 years". No numeric recovery was needed in this particular stochastic result; sentence-removal fallback remains offline-only verified. The first call passed, so the permitted second API call was not used.
- MiniMax education-date layout follow-up (offline only): the actual source stores school/location, degree and date in one paragraph with a long-space visual-row separator. The DOCX compact-layout spacing estimator used to insert an extra break before the date; it now measures only the degree on that visual row. With the retained real MiniMax bullets reinjected offline, the one-page PDF places the degree and date at the same y=669.9pt, with the date right-aligned at x=466.3pt. ATS readability flags match the previous verified report with no new warnings. Full offline regression: 292 passed; Ruff and `git diff --check` passed. No API calls were made for this fix.
- Final resume/Cover Letter formatting audit (offline only): recompiling the retained MiniMax Cover Letter with a modest 3em emergency stretch eliminated two approximately 4pt Overfull hboxes, with one page and no automatic word hyphenation. Recompiling the previously verified finance LaTeX resume after disabling automatic hyphenation removed three end-of-line broken words, kept source 120 and 8%, and remained one page without Overfull warnings. PDF visual metrics now combine text and graphics matrices, correcting the Cover Letter bottom coordinate from -557pt to approximately 213pt; resume geometry remained stable. Full offline regression: 293 passed; Ruff and `git diff --check` passed. No API calls were made, and previous delivery artifacts were not overwritten.
- Final sparse/CJK formatting follow-up (offline only): a resume item without organization/location no longer consumes an empty second row (heading-to-first-bullet gap fell from 25.1pt to 13.1pt), and empty skills groups are omitted. When the JD opens with a clear role title, Cover Letter metadata uses that literal title instead of a generic category; a CJK-capable font is selected only when the content needs it. The retained real MiniMax Cover Letter content recompiled with `大模型推理研发实习生` on one page, with complete extracted title and no Overfull or missing-character warnings. Missing glyphs now fail PDF compilation rather than silently dropping text. Full offline suite: 300 passed; Ruff and `git diff --check` passed. No API calls were made and prior verified outputs were not overwritten.
- Bilingual LaTeX resume follow-up (offline only): the resume template now uses the same conditional Noto Sans CJK SC / Microsoft YaHei font fallback as the Cover Letter. A synthetic Chinese candidate name, location, section and evidence bullet previously failed compilation due to missing DejaVu Serif glyphs; after the change it produced a one-page PDF with extractable Chinese text, no missing-glyph warnings and no Overfull hboxes. The English templates and other route tests remain unchanged. Full offline suite: 301 passed; Ruff and `git diff --check` passed. No API calls were made or prior verified outputs overwritten.

## Live API outcome expectation
The system should produce a single-page tailored resume, a single-page cover letter PDF, an application report, and a valid DOCX export with ledger metadata when the model output satisfies all evidence gates.

## Notes
- The live API remains sensitive to stochastic model output; if the model emits unsupported terms or misses primary metrics, the system intentionally rejects the output rather than relaxing the evidence gates.
- Recognized primary metrics are restored from the selected source item before rendering, and LaTeX overflow pruning protects metric-bearing bullets. This lowers stochastic failure rate while preserving the final integrity gate.
- This is intentional to preserve truthfulness and document quality.
