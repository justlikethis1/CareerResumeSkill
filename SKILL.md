---
name: jd-resume-cover-letter
summary: Enterprise-oriented evidence-bound JD analysis, tiered resume tailoring, dual-format cover letters, and safe LaTeX or OOXML document generation.
---

# JD Resume & Cover Letter Skill

Use this skill to prepare evidence-grounded applications for Quantitative Finance, Finance Operations, Systems/Infrastructure, AI Research, Data Engineering, HR/Recruiting, Administration, Customer Service, Hospitality/Food Service, Retail/Sales, and general Software roles.

## Non-Negotiable Rules

1. **Evidence is authoritative.** The Master CV is the only source of candidate claims. Never invent or expand metrics, dates, employers, institutions, papers, tools, ownership, or responsibilities. Keep unsupported requirements in `evidence_gaps`.
2. **Preserve verified quantities.** Keep source metrics and their meaning exact. Metric extraction covers common units and scientific notation such as `10⁶`, `10⁻⁶`, `1.2μs`, and `10000 QPS`; this is not a guarantee that every arbitrary notation is recognized. Do not omit a source metric just because a parser fails to recognize it.
	After model generation, the implementation deterministically compares primary metrics per selected source item and restores the original evidence bullet when a rewrite drops one. The model receives the per-item `REQUIRED_METRICS_BY_SOURCE_ITEM` checklist before generation. This repair occurs before rendering and remains subject to the same evidence, technology, page, and punctuation gates.
3. **Constrain company claims.** Use company-specific claims only from supplied `verified_company_context`. Without it, use `jd_only` technical alignment and do not assert company news, products, or strategy.
4. **Protect user documents.** For an existing DOCX resume, use the DOCX track. Do not rebuild its resume using the bundled LaTeX resume template. The injector preserves untouched package entries and controls only intended XML edits; it does not guarantee exact rendering of every Word feature or application.
5. **Treat model output as untrusted.** Use the schema/evidence-constrained tools. Report validation failures; never silently turn unsupported content into candidate facts.
6. **Honor the Chinese resume contract.** For `resume_language="zh_CN"`, write natural Simplified Chinese bullets whose final character is U+3002 `。`; ASCII period `.` is invalid. `lint_payload_bullets` now rejects it in Chinese mode. Preserve source item IDs, tools, and metrics. Never upgrade `参与` or `协助` to `主导`, `负责全盘`, or equivalent ownership claims unless the Master CV explicitly proves that responsibility. Do not infer scale, deployment, or model capabilities.
7. **Emit raw text, not LaTeX source.** Resume and Cover Letter JSON strings must contain literal candidate-facing text (`C#`, `C++`, `R&D`, `AT&T`, `M&A`, `user_id`, `100%`, `~10ms`, `^2`). Never pre-escape these as LaTeX (`C\#`, `loss\_fn`); the renderer applies `escape_latex()` once. Preserve a backslash only when it is itself part of a verified literal, not as formatting syntax.

## Role Archetypes and Projection Guardrails

Use the detected `role_type` to select framing, not to grant new qualifications. Apply a lexical projection only when the cited candidate evidence supports the underlying work.

| Role archetype | Evidence-supported framing | Never infer without source evidence |
| --- | --- | --- |
| `quant_fintech` | Latency, numerical precision, deterministic execution, backtesting, concurrency, risk | Trading P&L, live fund returns, order-flow scale, or production trading ownership |
| `finance_operations` | Financial reporting, reconciliation, budgeting, audit, compliance, accounts payable/receivable | Financial authority, regulated sign-off, or accounting ownership not evidenced |
| `systems_infra` | Throughput, scalability, memory/I/O bottlenecks, caching, production deployment | Distributed clusters, Kubernetes, or production ownership from a local prototype alone |
| `ai_research` | Training dynamics, preference alignment, policy/loss stability, evaluation, OOD robustness | PPO, GRPO, Ray, distributed training, or reward-model development unless explicitly evidenced |
| `data_engineering` | Pipeline reliability, data quality, orchestration, lineage, ETL, schema validation | Petabyte/global scale, streaming, or named orchestration tools unless evidenced |
| `hr_recruiting` | Sourcing, applicant tracking, onboarding, employee relations, HR operations | Hiring authority, confidential personnel decisions, or policy ownership not evidenced |
| `administration` | Calendar/travel coordination, office operations, records, scheduling, vendor coordination | Executive authority, budget ownership, or confidential access not evidenced |
| `customer_service` | Case handling, service recovery, complaint resolution, ticketing, customer communication | Unverified retention, CSAT, call volume, or escalation authority |
| `hospitality_food_service` | Front desk, reservations, guest service, food safety, POS workflows, shift coordination | Food-safety certification, revenue ownership, or supervisory scope not evidenced |
| `retail_sales` | Customer needs, point of sale, merchandising, inventory, account development, service | Sales quota, revenue, territory, or management claims not evidenced |
| `general_software` | Modular design, API contracts, integration, testing, delivery, user impact | Architect/lead ownership or production scale from implementation participation alone |

These are framing examples, not an allowlist of claims. Do not upgrade adjacent knowledge into hands-on experience, map SFT to PPO, infer distribution from parallelism, or turn a benchmark into live business impact. Preserve the distinction between a transferable skill and a verified skill.

**High-risk hallucination blacklist:** `FPGA`, `Kernel-bypass`, `DPDK`, `Sharpe`, `PnL`, `PPO`, `Ray`, and `Megatron`. Do not introduce these as candidate technologies, methods, or outcomes unless the Master CV explicitly documents that exact work and its context. A related JD keyword or adjacent experience is not evidence.

### Multi-Target Session Isolation

Treat each company/JD pair as an isolated application context. On a company switch, start a new application revision from the user's original complete `master_cv_json` or original template DOCX, not from a company-specific tailored payload or injected output. Invalidate and clear the prior `company_name`, `verified_company_context`, role-specific JD analysis, gaps, and cover-letter draft. Use only the newly supplied company/context; if no company is supplied, use `"Target Organization"` with empty verified context and `jd_only`. Never carry over prior-company claims, role labels, pain points, or keyword priorities. Preserve the prior company's deliverables as a separate application record; do not overwrite or repurpose them.

## Route First

Choose one resume-generation track based on the user's source document:

| User input / requirement | Track | Primary tool |
| --- | --- | --- |
| Existing `.docx` resume whose layout should be retained | A: DOCX in-situ | `generate_docx_application_package` |
| Structured Master CV JSON or greenfield resume | B: LaTeX | `generate_application_package` |

If a DOCX is supplied and visual fidelity matters, Track A takes precedence even if the user also provides extracted text. Do not send that resume through the standard LaTeX resume flow. Use granular DOCX tools only when the user requests intermediate review or a required dependency blocks the end-to-end package.

### Default vs. Granular Calls

- **Single-shot execution budget:** for a new full-application request, the first tool round has a budget of exactly one MCP call: `generate_docx_application_package` for Track A or `generate_application_package` for Track B. Do not parallelize preflight, layout, JD, tailoring, injection, or compile tools before the package call. If that call fails, diagnose only the reported blocker in a subsequent tool round. Exception: use a granular tool first only when the user explicitly asks for a staged inspection, layout audit, or diagnostic rather than the complete package.
- **Human-in-the-loop path:** use granular tools only when the user asks to inspect/review an intermediate result, approves work in stages, or a dependency prevents the end-to-end package. Explain which artifacts that partial path can and cannot produce. Do not mix Track A and Track B for the same resume unless the user explicitly changes the layout requirement.

### Clarify Before Calling

The end-to-end package tools require a JD and a source CV. A JD may be supplied as text or a public HTTP(S) URL. If the JD cannot be fetched or is invalid, ask for pasted JD text. Ask for a missing source CV because candidate claims cannot be grounded without it.

`company_name` is a required tool argument, but its absence is not a reason to interrupt the user: pass the neutral display value `"Target Organization"`, leave `verified_company_context=""`, and use the backend's `jd_only` company-claim policy. Do not infer a real employer or company details from the JD. If a later response supplies the company name, use it on the next generation or requested update. Tone and application date may use tool defaults.

The resume source tools accept DOCX or structured Master CV JSON, not a PDF resume. If the user provides only PDF, explain that this skill cannot import it as an editable/layout-preserving source; ask for the original DOCX or a verified Master CV JSON. Do not imply that PDF layout can be cloned. If the user authorizes using extracted/pasted PDF text, first map it into the Master CV JSON structure and have the user confirm the resulting facts; only then use Track B.

## Rewrite Contract

Treat the generated `item_bullet_budgets` as authoritative. Relevance determines the dynamic pyramid; do not allocate the same number of bullets to every experience. The target is 8-11 experience bullets when the available evidence and per-item budgets allow it; never invent or duplicate evidence to reach a count. Before DOCX injection, truncate every item's generated bullet list to its budget maximum. A fidelity fallback replaces the current bullet in place; it must never append a restored source bullet or retain a duplicate.

| Tier | Typical bullet budget | Intensity | Required behavior |
| --- | ---: | --- | --- |
| Tier 1: highest-relevance / hero evidence | 3-4 | Level 3 `full_lexical_projection` | Use action-first STAR and relevant JD terminology, but only where the cited evidence supports it. Preserve the exact underlying facts, tools, and metrics. |
| Tier 2: supporting evidence | 2 | Level 2 `strategic_re_anchoring` | Reorder clauses and shift framing toward a supported JD need. Keep core tools, methods, and every metric. |
| Tier 3: ancillary evidence | 1 | Level 1 `polish_only` | Improve grammar, weak verbs, or redundancy. Keep a clear source sentence nearly verbatim; do not force STAR or novelty. |

For AI or systems targets, verified LLM, SFT, RLHF, DPO, multimodal, or post-training evidence receives a deterministic Tier 1/Tier 2 floor when the source supports it. This is a prioritization rule, not permission to promote adjacent knowledge or unsupported JD mechanisms. Never raise rewrite intensity to satisfy an unsupported JD requirement. Every generated bullet must cite evidence from its own source item; skills must remain a subset of the Master CV. Unsupported model-generated skill labels are omitted and surfaced as evidence gaps, not promoted to candidate facts. Resume bullets are plain text, not Markdown, and must not contain decorative bullet symbols or padding.

**Syntactic integration rule:** integrate each tool/keyword into a grammatical action sentence as its subject, object, or a meaningful prepositional phrase (for example, "used X to reduce Y"). Do not append comma-separated keyword lists, parenthetical skill dumps, tags, or verbless noun strings to bullets or profiles. Prefer natural, evidence-complete wording over increasing the heuristic ATS coverage; never distort a sentence to chase a percentage. ATS coverage is a diagnostic, not a writing objective or ranking guarantee.

**Exact Lexicon Grounding:** the backend may provide `EXACT_SUPPORTED_JD_PHRASES` for phrases whose underlying method and result are supported by cited evidence. Use those phrases naturally once when they improve clarity, such as `latency optimization` for measured inference latency or `reliable inference pipeline` for a documented inference workflow. Do not copy a JD phrase when it implies unsupported scale, deployment, ownership, or mechanism. Singular/plural pipeline and workflow variants may be reported as transparent ATS aliases, not as new candidate facts.

## Track A: DOCX In-Situ

Use `generate_docx_application_package` for the complete DOCX route. It imports the source DOCX, analyzes the JD, allocates item budgets, tailors evidence, injects bullets into the source template, converts and verifies the resume PDF, and creates Cover Letter PDF, TXT, and Markdown artifacts.

MCP signature (argument names, order, types, and defaults are part of the contract):

```python
generate_docx_application_package(
	docx_source: str,
	jd_text: str,
	output_docx: str,
	company_name: str,
	tone: str = "professional and concise",
	verified_company_context: str = "",
	resume_language: str = "en",
	application_date: str = "",
	layout_strategy: str = "fast",
)
```

`resume_language` accepts `"en"` or `"zh_CN"`; Chinese DOCX resume generation requires an available LLM provider. The end-to-end tool has no `compile_documents` switch. Internal helpers such as `inject_docx_bullet_groups` and `refine_one_bullet` are not MCP tools; do not call them directly. Other low-level MCP tools are exposed for explicit staged work, but their availability does not override the single-shot default.

1. For a normal full-package request, call the package tool first; do not spend the single-shot budget on a speculative `check_environment`. Call `check_environment` only when the user explicitly requests diagnostics or after a package failure identifies an environment blocker. The package requires a usable DOCX-to-PDF converter and a LaTeX compiler for the Cover Letter PDF.
2. Pass the original DOCX path, full JD, a distinct output DOCX path, and company name. Supply `verified_company_context` only when it is actually verified. `resume_language="zh_CN"` requires an available LLM provider; `application_date` is optional and defaults to the current local date.
3. Review `item_bullet_budgets`, `preflight`, `quality_report.integrity_linter`, `quality_report.pages`, `ats_report`, `refinement`, and `skipped_replacements` in the result. The package must pass its one-page resume integrity check to return successfully.
4. Use the unified delivery contract below to report returned artifacts and validation results. Do not dump the raw result object.

The default `fast` strategy verifies level 2 first for crowded sources, but starts at level 0 when the source PDF is one page and its estimated source paragraphs occupy at most 25 lines. If the tailored PDF then overflows, it still tries levels 1 and 2. Pass `layout_strategy="baseline"` to preserve the previous unconditional level 0→1→2 order and prefer the least compact one-page result; this remains callable as a rollback path when layout fidelity matters. The geometry threshold is a heuristic, never a replacement for PDF page verification. Level 2 applies global 215-twip body line spacing and bounded 144-twip top/bottom margin reductions with a 540-twip floor. Section headings retain `keepNext` and a minimum 4pt paragraph separation; a 3%-10% bottom-whitespace range is considered visually comfortable. If strict level 2 still overflows, either strategy may use the auditable heading-protection relaxation before requesting one evidence-bound bullet patch. Every candidate must pass the actual PDF page and integrity gates; do not claim the process will always reduce the document to one page.

For an intermediate/manual DOCX workflow, use `inspect_docx_layout` or `import_docx_master_cv` to obtain paragraph IDs and source mapping, then use the relevant tailoring and injection tools. Treat paragraph IDs as the only valid replacement keys. Never synthesize unstyled Word paragraphs or bypass the source evidence mapping.

In a granular DOCX-only fallback, inspection/injection may produce a DOCX without PDF verification. Do not promise Cover Letter PDF/TXT/Markdown files unless a tool actually returned those paths; the end-to-end package writes the letter files only after its PDF conversion stages complete.

## Track B: LaTeX

Prefer one `generate_application_package` call with the complete Master CV JSON, full JD, and company name. Set `page_limit=1` unless the user asks for another limit. The package returns tailored content and reports; use the unified delivery contract below for artifacts and acceptance.

MCP signature:

```python
generate_application_package(
	jd_text: str,
	master_cv_json: dict[str, Any],
	company_name: str,
	tone: str = "professional and concise",
	verified_company_context: str = "",
	application_date: str = "",
	page_limit: int = 1,
	compile_documents: bool = True,
)
```

`master_cv_json` MUST be a parsed JSON object (`dict[str, Any]`), never a file path string or serialized JSON string. If the user points to a `.json` file, read and parse it into a dictionary before invoking the tool; if the file is unavailable, ask the user to upload or paste the JSON. Validate that the parsed object follows the Master CV shape before calling.

For a granular workflow, call `analyze_job_description`, then `tailor_resume_content`, then `draft_cover_letter`; render the resume and letter using the bundled `resume` and `cover_letter` templates. Do not place unescaped model text directly into LaTeX.

Use this granular path only for staged review. `compile_documents=false` is an end-to-end package option, not a general compiler fallback for Track A.

When compiling, the renderer tries compact levels 0, 1, and 2, using the DOCX fast-path heuristic where applicable. If the resume still exceeds its page limit, it may remove lower-priority resume bullets/items and records those actions in the compile result's `attempts`; cover-letter content is not pruned by this resume-specific step. Treat a compile error or page-limit failure as a failed delivery, not a successful PDF.

## Cover Letter Contract

The output schema requires **exactly three prose paragraphs**. Do not add a fourth paragraph or convert the body to bullets. The English drafting target is 280-340 words total, with these paragraph budgets:

| Paragraph | Target words | Content |
| --- | ---: | --- |
| 1 | 50-70 | Role/company hook, verified specialization, and value against a primary JD pain point |
| 2 | 140-175 | A distinct evidence-backed technical story; do not repeat the opening metric or central claim |
| 3 | 60-80 | Evidence-supported team/role alignment and a concise invitation to discuss |

`CoverLetterDraft` enforces exactly three paragraphs and defensive word-count bands: 45-80, 115-195, and 50-90 words (210-350 total). Paragraph drafting targets remain 50-70, 140-175, and 60-80 words (280-340 total). The second and third paragraph hard minima allow five words of generation variance below target; the total floor equals the sum of paragraph minima and adds no separate padding requirement. The hard range is shared by model validation and `quality_report.typography_audit.cl_within_target_range`; a letter within each paragraph band and at least 210 total words can pass the defensive gate when evidence checks pass. For a word-count repair, add the deficit plus a 10-word margin using distinct cited evidence; do not repeat another paragraph's claim or metric. Cover Letter underflow may receive a bounded set of additional schema-repair attempts; these attempts may only add source-supported content. Abbreviated calibration examples and the deterministic offline fallback are explicitly exempt. Keep company-specific claims within `verified_company_context`; otherwise use JD-only technical alignment. If the user asks for another structure or length, explain the schema contract before changing the workflow.

## Delivery, Acceptance & Reporting Contract

Report success only when the selected route's returned page count meets its configured limit (default: one page), the applicable integrity report passes, and cited evidence and source metrics remain supported. Mention glyph, extraction, or parseability warnings when reported. A skipped compilation is not PDF verification; never claim `100%` metric invariance or screening success.

Never print the raw MCP result dictionary. Use one concise response, populate only values actually returned, and omit unavailable artifacts:

```text
### Application Package
- Company / role: <provided value, or "Target Organization" placeholder / not specified>
- Route: <DOCX in-situ | LaTeX>
- Resume: <DOCX path for Track A; PDF path when compiled; TEX path only if returned>
- Cover Letter: <PDF path when compiled; TXT and Markdown paths when returned>
- Validation: <page count / configured limit; integrity status or not run; warnings>
- ATS heuristic: <hard/preferred keyword coverage and exact/semantic matches, if returned>
- Evidence gaps: <explicit missing core requirements; distinguish from preferences>
```

Track A paths come from `output_docx`, `output_pdf`, `cover_letter_pdf`, `cover_letter_text_path`, and `cover_letter_md_path`. Track B with `compile_documents=true` reports returned `documents.resume` and `documents.cover_letter` PDF/TEX paths plus the two cover-letter text paths. Track B with `compile_documents=false` reports structured results and TXT/Markdown paths only; do not list PDF/TEX paths. For blocked or partial runs, identify the blocker and list only artifacts actually returned.

Always surface `gap_analysis.gaps` and `evidence_gaps`; cross-check `ats_report.hard_requirements.missing` and `ats_report.preferred_keywords.missing` when present. Describe ATS values only as deterministic local keyword coverage. Do not say "95% match", promise to pass screening, claim compatibility with a proprietary ATS, or imply that keyword coverage predicts hiring outcomes. If a report is absent, state that it was not produced.

## Page-Budget Recovery Rules

These transitions are automatic inside the package tools; internal helpers are not MCP tools. The Agent must call the public route and inspect its returned state, not simulate the internal loop.

| Route/state | Guard and transition | Success or stop condition |
| --- | --- | --- |
| DOCX: initial PDF has one page | Run the package integrity gate. | Return only if integrity passes. |
| DOCX: overflow | Default `fast` starts at level 2 for crowded sources, or level 0 for short one-page originals; `baseline` always starts at level 0. When starting at 0, try level 1 then 2 on overflow. Preserve heading breathing room and `keepNext`; after level 2 overflow, use bounded heading relaxation and evidence-bound repair. | If one page and integrity pass, return; otherwise continue to content repair if available. |
| DOCX: still over limit and LLM provider available | Propose one evidence-bound bullet patch, re-inject, and verify. | Accept only if source facts/metrics/technologies remain supported, the patch passes fidelity checks, geometry improves, and final page/integrity gates pass. Otherwise block success. |
| DOCX: still over limit without an available/accepted patch | Do not rewrite the whole resume. | Report overflow; do not label it a successful one-page package. |
| LaTeX: page-limit error at compact level 0 or 1 | Retry at the next compact level, up to level 2. | Return if the configured page limit is met. Other compiler errors do not enter recovery. |
| LaTeX resume: still over limit at level 2 | Prune a lower-priority resume bullet/item and retry at level 2, up to 64 attempts. | Return only if the limit is met; actions appear in `attempts`. If exhausted, report failure. |
| LaTeX cover letter: still over limit at level 2 | No content-pruning loop is available for the letter. | Report the page-limit failure; do not silently rewrite or truncate it. |

## Lifecycle Diagnostics and Incremental Updates

### Phase 1: Pre-flight and Input Guards

| Condition | Action |
| --- | --- |
| JD missing or public URL fetch fails | Ask for JD text or another valid public HTTP(S) URL; never bypass URL safety checks. |
| Source CV missing | Ask for DOCX or complete Master CV JSON; a JD is not candidate evidence. |
| Company name missing | Use `"Target Organization"`, empty verified context, and `jd_only`; disclose the placeholder in the final response. |
| PDF is the only resume source | Ask for original DOCX or verified Master CV JSON. Use extracted text only after user confirmation and conversion into the Master CV JSON structure. No PDF import/layout-preservation tool exists. |
| `master_cv_json` is a path or serialized string | Read/parse and validate it as a JSON object before calling Track B; ask for upload/paste if inaccessible. |

### Phase 2: Environment and Tool Degradation

| Condition | Action and boundary |
| --- | --- |
| `DEEPSEEK_API_KEY` absent | Check `check_environment`; identify English output as deterministic fallback, not LLM tailoring. `zh_CN` DOCX generation requires an available provider. |
| LaTeX compiler unavailable | Track B may run with `compile_documents=false`; it returns structured results and TXT/Markdown, but no compiled PDF/TEX paths. Track A has no equivalent switch and cannot complete its Cover Letter PDF step. |
| DOCX-to-PDF converter unavailable | Use granular inspection/injection only for a clearly labeled DOCX-only partial result. The end-to-end package may fail before returning Cover Letter artifacts; do not promise those paths or PDF verification. |
| Output directory unwritable or required dependency missing | Use `check_environment`, resolve the reported readiness issue, then retry. Do not alter resume claims to work around environment failure. |

### Phase 3: Quality Gates and Delta Boundaries

| Condition | Action and boundary |
| --- | --- |
| Page limit remains unsatisfied | Follow the route's recovery table; disclose unresolved overflow and attempts. Never silently truncate facts, rewrite the entire resume, or increase the limit without authorization. |
| Metric, technology, or evidence integrity fails | Restore source-supported content or remove the unsupported rewrite, then rerun the relevant validation. Do not present the artifact as verified. |
| ATS report has missing hard requirements | List them as evidence gaps and keep them out of candidate claims; do not promise screening success or add unsupported keywords. |
| Requested change affects one bullet only | Use the delta protocol below; do not rerun full analysis/tailoring or regenerate approved content. |
| Requested change alters evidence, metrics, target role, or multiple sections | Explain that it exceeds a local delta and confirm before full retargeting. |
| `TextLengthBudgetError: Replacement for <paragraph_id> needs <n> rendered lines; ... budget is <m> lines` | Parse the exact paragraph ID and measured/budget line counts. Shorten only that replacement while preserving its source evidence and metrics; retry from the latest DOCX snapshot with a new output path and the default length gate. |
| `ReplacementNotFoundError: Unknown paragraph IDs: [...]` | Do not guess or retry the stale ID. Refresh the current document's mapping with `inspect_docx_layout` (or re-import with `import_docx_master_cv` if the source-item mapping is also needed), then target a returned ID. |
| `ValueError: Generated content contains unsupported metrics: [...]` | Treat each listed metric as an unverified claim. Compare it with the source evidence; remove it or restore the exact source-supported value, then rerun the relevant generation/validation. Never infer a replacement metric. |

**Linear Snapshot Chain and Latest Approved Baseline (LAB) protocol:**

1. Keep a monotonically increasing revision (`r1`, `r2`, ...), with a current snapshot pointer and a separate validation state (`pending`, `passed`, or `failed`). Every successful mutation/render immediately advances the current snapshot pointer to its new output and associated content state. Never silently reset it to the original resume or an older revision.
2. Mark a snapshot **Approved** only after its route-specific validation passes. An injected DOCX or rendered document whose validation is pending/failed is still the current working snapshot, but must not be reported as a verified delivery. A failed check does not authorize reverting: repair from that latest snapshot, or ask the user before an explicit rollback to a named revision.
3. Every subsequent delta inherits the immediately preceding current snapshot. Keep each revision's artifact path and exact content payload associated in session state; report the latest Approved revision separately from any pending candidate.
4. **DOCX:** find the paragraph ID from the preceding snapshot's mapping or inspect its DOCX. Call `inject_docx_layout` with the immediately preceding DOCX as `source_path`, a new revision-specific `output_path`, and exactly one entry in `replacements`; keep `enforce_length_budget=true`. As soon as injection succeeds, set that output path as the current snapshot. Then call `compile_and_verify_pdf` using it. Only after PDF verification passes may it be marked Approved. Every later injection must use the latest snapshot's DOCX path, never the original resume.
5. **LaTeX:** `render_and_compile_latex` accepts a JSON payload, not a prior PDF/TEX path, and its MCP signature has no revision-directory argument. Keep the exact payload associated with each revision; edit only the requested bullet and render that payload with the same page limit. On successful compilation, immediately advance the current snapshot to the returned render paths plus the exact payload used; mark it Approved only after applicable validation passes. If `attempts` records automatic bullet/item pruning, reconcile those removals into the saved payload before the next delta. If reconciliation is impossible, stop and ask; never reuse an older payload. Do not claim immutable physical files unless a separate versioned copy was actually created.

Do not call internal `refine_one_bullet` from MCP; it is not an exposed tool. Granular LaTeX rendering reports compile/page-budget results, not package-level ATS or integrity checks. Do not claim those checks passed without their actual reports. A request requiring full package-level verification may rerun tailoring, so explain that impact and get approval first.

### Exception Signature Triage

Parse the exception type and quoted fields above before choosing a retry. Do not blindly repeat the same call, expose a raw traceback as the entire user response, or fabricate missing identifiers/counts. If an error does not match a known signature, report the concise error and stop for diagnosis; retry only after the cause or input is corrected.

## Master CV and Credentials

Use [examples/master_cv.template.json](examples/master_cv.template.json) as the input shape. `examples/master_cv.json` is synthetic test data, not a real candidate profile. Keep the complete source evidence available; a shortened CV can make omitted facts unrecoverable.

Keep `DEEPSEEK_API_KEY` only in the ignored root `.env` file. Never put credentials in source, MCP configuration, prompts, reports, or examples. Use `check_environment` for secret-free readiness diagnostics.