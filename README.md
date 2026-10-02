# Career Resume Skill

基于 DeepSeek（OpenAI-compatible API）的端到端 MCP Skill，面向香港 Quant/FinTech/投行科技部以及大湾区/全球 AI Lab。它支持 JD 文本或公网 URL，完成证据化 Gap Analysis、真实性约束的简历重构、Cover Letter 生成，以及 ATS 友好的 LaTeX 单页渲染与 PDF 编译。

岗位分类覆盖 `quant_fintech`、`finance_operations`、`systems_infra`、`ai_research`、`data_engineering`、`hr_recruiting`、`administration`、`customer_service`、`hospitality_food_service`、`retail_sales` 和 `general_software`。同一份真实经历会按目标岗位投射到不同业务痛点，但不会新增未验证工具、职责或指标。`technology_terms.json` 同时覆盖技术栈、财务/HR 系统、CRM、客服平台、办公协作、POS/PMS 和合规工具；行业软技能仍由证据文本支持，不会被伪装成技术词。

同时支持基于原始 OOXML 包的 DOCX 版式检查与原地回填：保留原文档的字体、表格、图片关系和未修改 XML，不把 Word 简历重建成一个新模板。

## 设计边界

- Master CV 是候选人事实的唯一来源；未出现的指标、日期、论文、雇主、技术和职责不会被补写。
- DeepSeek 输出中的新数字会被 claim ledger 拒绝，包括 JSON 数值字段。
- 公司特定动机只允许来自显式传入的 `verified_company_context`。
- 模型文本不直接生成 LaTeX，所有内容经统一转义后注入受控模板。
- 每个项目和改写 bullet 必须引用稳定 evidence ID；项目身份、机构和日期由 Master CV 回填。
- DeepSeek 输出经过 Pydantic JSON Schema 校验，首轮结构错误会触发一次受约束修复。
- 经历按相关度进入三级 Rewrite Intensity：弱相关仅润色、支撑经历战略重锚、核心经历全量术语投射；各级都保留来源事实和指标。
- 对 AI/Systems 岗位，包含已验证 LLM、SFT、RLHF、DPO、多模态或后训练证据的经历具有 Tier 1/Tier 2 最低预算保底，不会仅因关键词排序被压缩为单条 Tier 3 bullet。
- 主要指标通过 `REQUIRED_METRICS_BY_SOURCE_ITEM` 传给模型，并在模型输出后按 source item 确定性恢复；LaTeX 超页裁剪保护指标 bullet，最终 PDF 仍必须通过指标不变性门禁。
- Exact Lexicon Grounding 通过 `EXACT_SUPPORTED_JD_PHRASES` 只向模型提供由证据支持的 JD 原子词组；单复数 pipeline/workflow 变体通过透明 ATS alias 处理，不以虚构经历换取关键词覆盖。
- Level 1 可以保留已经清晰且符合预算的原句；词汇重合度低于 0.60 时回退到最接近的原始 bullet，并在 `rewrite_fidelity` 中告警。Level 3 高重合度仅给出诊断。
- 简历 Few-Shot 按 JD 原型只注入 1 条领域正反例和 1 条 Level 1 正反例；正例符合 `GeneratedResumeItem` Schema、使用隔离的 `example:` ID，并在测试中核对来源技术和指标。无公司背景的求职信额外获得一条 `CoverLetterDraft` 形状的纯技术论证示例。库存放结构化数据，发往模型的是较紧凑的四要素文本；实际 token 成本取决于模型 tokenizer，不能保证固定为 150–200 tokens。示例均为合成数据，不得作为候选人事实；不会复制第三方 LaTeX 模板的经历，也不宣称这些模板经商业 ATS 认证。
- 未配置 API Key 时使用明确标记的确定性降级，不伪装成模型定制结果。

## 凭证边界

| 功能 | 真实 DeepSeek API Key | 说明 |
| --- | --- | --- |
| 规则 JD 分类、ATS 关键词、Gap/Evidence 分析 | 不需要 | 本地确定性逻辑 |
| Master CV schema 校验、排序、Bullet 裁剪 | 不需要 | 本地执行 |
| JD 公网 URL 抓取 | 不需要 | 仅请求公开 HTTP(S) 页面 |
| DeepSeek 增强 JD 抽取 | **需要** | 调用 `DEEPSEEK_API_KEY` |
| LLM 简历 Bullet 重写 | **需要** | 调用 `DEEPSEEK_API_KEY` |
| LLM Cover Letter 定制 | **需要** | 调用 `DEEPSEEK_API_KEY` |
| LaTeX 源码渲染 | 不需要 | 本地模板和转义 |
| PDF 编译 | 不需要 API Key | 模板使用 `fontspec`，需要 `tectonic`、`xelatex` 或 `lualatex`；含中文时还需要 Noto Sans CJK SC 或 Microsoft YaHei 字体 |

本地凭证只放在根目录 `.env`，该文件已被 `.gitignore` 忽略。请编辑 [`.env`](.env) 填入真实值；不要把 Key 写入源码、MCP JSON、README、测试、报告或聊天记录。仓库中提交的是 [`.env.example`](.env.example)，其中不含凭证。

## MCP Tools

| Tool | 输入 | 输出 |
| --- | --- | --- |
| `analyze_job_description` | `jd_text` | 岗位类型、Must/Nice-to-have、ATS 关键词、业务场景等 |
| `tailor_resume_content` | `master_cv_json`, `jd_analysis` | 重排和改写后的模块、Gap Analysis、证据缺口 |
| `draft_cover_letter` | `tailored_cv`, `company_name`, `tone`, `verified_company_context` | 三段式 Cover Letter JSON |
| `render_and_compile_latex` | `tex_template_name`, `content_json`, `page_limit` | PDF/TEX 路径、页数、编译器、日志、紧凑度级别 |
| `generate_application_package` | JD、Master CV、公司、语气、日期、页数 | 一次返回分析、Gap、简历、信件和两份文档 |
| `inspect_docx_layout` | `.docx` 路径 | 字体/段落/样式继承/多 section/表格/页眉页脚/文本框/图片锚点与媒体缓存清单 |
| `audit_cv_health` | 原始 `.docx` 路径 | 无需 JD/模型，报告当前内容的预计行数、词容量、私有区字形和表格宽度风险 |
| `calculate_layout_budget` | `.docx` 路径 | Pillow 字体宽度、可用行宽和预计折行数；附目标 85%-92% 行宽，不使用字符串长度比例 |
| `inject_docx_layout` | 原文档、paragraph ID → 新文本 | 保留原 ZIP 包和媒体的回填 `.docx` |
| `inject_docx_in_situ` | 原文档、paragraph ID → 新文本 | 纯 OOXML 确定性注入，无 LLM 调用 |
| `convert_docx_to_pdf` | 回填后的 `.docx` | Word 或 LibreOffice 输出 PDF，并执行排版伪影净化 |
| `compile_and_verify_pdf` | `.docx`、源证据文本、bullet | PDF 页数、关键指标、标点和字形检查 |
| `check_environment` | 无 | API、依赖、Tectonic、LibreOffice 和输出目录状态，不返回密钥 |
| `generate_tailored_payload` | Master CV、JD 分析 | schema 校验后的纯文本 DTO，并通过 MCP logging 汇报阶段状态 |

| `generate_docx_application_package` | 原始 `.docx`、JD、输出路径、公司名、语气、公司背景 | 基于原 Word 模板的 Resume DOCX/PDF + 针对 JD 的 Cover Letter PDF |

DOCX 注入还会经过 `docx_sanitizer.py`：词法层清理不可见字符和尾部填充，OOXML 层清除普通正文的 tab 并禁用样式 leader；具有明确右对齐制表位且 tab 后有文本的公司/地点标题保留对齐，独立长空格分隔符改为右对齐 tab。Harness 将 PDF 抽取文本中的连续尾部破折号作为硬失败。

实习与项目经历的地点始终以行的右侧制表位为锚点：DOCX 当组织名与长地点按字体宽度估算不足以留出至少 12pt 间距时，在地点前有界换行，地点仍靠右；短地点保持同排。LaTeX 简历使用独立的左右列，长组织名在左列、长地点在右列各自换行，二者不会挤到同一列；最终仍以实际 PDF 单页验证为准。LaTeX 简历与 Cover Letter 均禁用英文单词的自动跨行断词，并通过有界的应急行宽避免长词挤出右边界；PDF 单页和指标校验仍不放松。

LaTeX 简历仅在经历确有组织或地点时渲染第二行，空技能分组不产生空标题。求职信主题优先使用 JD 开头明确写出的岗位名称（如 `Job Title:` 或简短的岗位标题行），否则回退到职位类别；含中文的 LaTeX 简历或求职信选择已安装的 CJK 字体，没有可用字体或编译日志报告缺字时明确失败，不交付看似成功但实际缺字的 PDF。字体与排版调整均需通过单页实际 PDF 编译。

教育经历若在同一原始 DOCX 段落中用长空格排出学校/地点和学位/日期两行，宽度判断只测日期 tab 前当前视觉行的学位文字；不再错误地把学校与地点也算进去并为日期另加空行。回填后的日期仍靠右，与学位同一行，并位于上一行地点的正下方。

JD 分析只注册 `analyze_job_description` 一个 MCP 工具；旧 `analyze_target_jd` 别名已移除。公网 URL 的每一跳都会重新校验 DNS 结果，并将连接固定到已校验的数值 IP，同时使用原 hostname 完成 TLS SNI/证书校验。

申请包同时返回 `ats_report`（Resume + Cover Letter 的硬技能/优选词精确与语义覆盖、缺项，并保留 `resume_only` 子报告用于单独查看简历缺口）和 `fact_cards`（事实原文、技术词、已验证数字及 Evidence ID）。中文长句要求会保留在 `excluded_non_atomic_requirements` 审计字段中，不作为单个 ATS 关键词计分；直接 ATS 评分也会再次执行原子短语过滤，避免绕过应用层分析。DOCX 注入前每个 item 的 bullet 列表受 `item_bullet_budgets` 硬截断，fidelity 回退只做原地替换。ATS 分数是本申请包的透明关键词覆盖启发式值，不代表任何商业 ATS 排名或录用概率；现实 ATS 对求职信的计分权重各异，因此同时保留 Resume-only 子报告，且不会以虚构补词提升分数。PDF 交付前还会运行 Integrity Linter：单页预算、被引用证据中的指标不变性、未授权技术/高危黑名单、尾部破折号和私有区字形。

申请包报告的 `performance` 字段记录 `total_seconds` 与 `stages_seconds` 固定阶段耗时，用于定位模型、DOCX 排版/PDF 编译和质检耗时；仅包含阶段名与数值，不记录 JD、简历正文、API Key 或模型响应。DOCX `fast` 模式的 `jd_analysis_and_layout_budget` 与 `tailoring_cache_refinement_and_preflight` 与原件 PDF 转换并行，`source_baseline_wait` 是定制后仍需等待原件转换的时间；`resume_injection_and_pdf_attempts` 含与首次 PDF 导出重叠的求职信首稿时间，`cover_letter_generation_and_source_baseline` 只计候选验证后仍需执行的工作（可能为零）。`refinement.initial_cover_and_pdf_overlap_seconds` 记录从两项任务同时启动到都完成的墙钟时间，并非精确的共同运行时长，不能与 PDF 耗时相加。若超页后的证据补丁被接受，首稿会丢弃并根据最终简历重写，`refinement.cover_letter_redrafted_after_patch` 标记该情况。

PDF 的底部留白诊断会合成文字矩阵与图形变换矩阵；忽略后者会把部分 LaTeX 求职信的实际签名位置误报为负坐标或零留白。该诊断只用于视觉评估，不以简历的 3%–10% 目标强制约束正式求职信的留白。

求职信严格为三段；Pydantic 校验段落词数区间为 45-80、115-195、50-90，总计防御区间为 210-350 词，提示目标仍为 280-340 词。技术段和结尾段下限各比先前放宽 5 词，用于容纳模型计数波动；总下限等于三个段落硬下限之和，不额外要求填充。证据、技术和指标校验仍然严格。申请包同时生成 UTF-8 纯文本和 Markdown，并分别通过 `cover_letter_text_path` 与 `cover_letter_md_path` 返回路径。模型生成的简历和求职信只对来源证据中出现的技术词规范大小写；词表在 `src/career_resume_skill/technology_terms.json`，不会把 JD 里的新工具加入候选人事实。求职信签名由模板排版，PDF 测试会拦截 `extbf` 字样泄漏。示例配置在 `src/career_resume_skill/templates/few_shots.json`，高危术语在 `src/career_resume_skill/hallucination_blacklist.json`；修改配置后需通过 Schema/事实测试。新增岗位原型仍需扩展 Pydantic 的 `role_type` 枚举。

模型生成的无来源数字在简历和求职信的现有两轮重写窗口内只能按来源修正，不能直接放行。求职信模型现在接收按 evidence ID 列出的来源数字，并被明确禁止从任职日期推算年限或采用仅在 JD 出现的指标；这只是生成约束，不替代最终校验。真实性扫描排除 `source_item_id`、`evidence_ids` 等机器标识，避免把 `bullet:2` 错判为经历指标，但正文和结构化数值字段仍严格检查。若简历第二轮仍有无来源数字，只恢复受影响的来源 profile 或对应经历 bullet，写入 `evidence_gaps` 后再次运行全局真实性校验。求职信第二轮仍带无来源数字时，仅允许移除不含任何来源指标的完整句子，且必须重新通过三段词数、Critic、技术来源和最终真实性校验；否则仍拒绝交付。来源中带明确业务对象的工作量（如发票、工单、客户 case 数）与百分比等指标一样，进入相应经历的保留预算和 LaTeX 超页裁剪保护；预算不足以同时保留时会失败，不静默覆盖。同输入的财务岗位端到端路径已通过实时 API 测试；持续虚构数字后的删句回退在该次运行中未触发，仍仅有离线验证。

DOCX 申请包经历 `INGESTION → PROJECTION → GEOMETRIC_EVALUATION → DOCX_INJECTION → HEADLESS_VERIFICATION`；预渲染几何仅评估，不因单条偏长就截断。默认 `fast` 策略对拥挤模板先尝试 level 2；当原件 PDF 为 1 页且源段落估算总行数不超过 25 行时先试 level 0，若定制后超页则依次尝试 level 1/2。原有 `baseline` 始终按 level 0→1→2 试探，优先保留原生样式。几何阈值只是节省尝试的启发式判断，不代替实际 PDF 单页验证；需要优先保留复杂模板视觉间距时请选 `baseline`。level 1 收紧继承段落间距与行距，level 2 使用 215 twips 行距并有界收缩上下页边距，同时保留标题 `keepNext` 和最小呼吸间距。视觉底部留白 3%~10% 视为舒适区；若严格 level 2 仍无法单页，仅允许放松标题额外间距作为可审计兜底，不放松证据、指标或页数门禁。随后才进入 `TARGETED_RE_RANKING`：优先选择可节省行数的 Tier 3/Tier 2 bullet，一次只缩短一条，再从原始 DOCX 注入并终验。若补丁丢失来源指标、已知技术、引入未经验证的数字、违反 Level 1 保真或没有减少占宽，则拒绝并保留原文。模型不可用时不伪造微调；重试仍非单页则阻断交付。`refinement.pdf_attempts` 记录各候选的紧凑级别、实际页数和转换耗时，不含简历正文。

CLI 回退到原版式顺序：在 DOCX 生成命令后附加 `--docx-layout-strategy baseline`；省略该参数即使用 `fast`。MCP 工具 `generate_docx_application_package` 可传 `layout_strategy="baseline"`，Python 服务方法也接受相同参数。两种模式均执行相同的证据、页数、Critic 和 Integrity 门禁；基线实现仍可直接调用，不需要覆盖优化版输出。`fast` 会将原始 DOCX 的基线 PDF 转换与 JD 分析及简历定制重叠，再将求职信首稿与首个简历候选 PDF 转换重叠；简历候选转换之间仍顺序进行。草稿使用简历快照，若后续单条 bullet 修补被接受则重新生成，不会交付基于旧版简历的信。

超页时会在临时目录生成 level 1/2 候选，不把 `-compact`、`-compact-deep` 或 `-retry` 中间文件泄漏到交付目录；最终通过的候选会原子复制到配置的 `output_docx` 及同名 PDF。只有重新导出的 PDF 确实变成单页才采用，否则再进入单条文字微调。这是有界尝试，不保证某个比例的超页都能吸收。Pillow 的 `orphan_words` 会标记英文 bullet 末行仅有 1–2 词，供局部修补参考，不会自动往句尾填充文本。

注入前 `preflight` 在内存中检测 bullet 的单句号、异常空白、私有区字形和实际引用来源的指标；导出后仍由 PDF 页数、可提取文本和指标完整性终验。`quality_report.ats_readability.ats_readability_flags` 会提示标题顺序倒置、机构/日期与标题分离及 bullet 无法连续提取等风险，**不等于 Workday/Taleo 兼容认证**。Pillow 按原 DOCX 首 Run 的真实 Regular/Bold 字体估算整个替换句子的宽度（不会凭 `**` 假设局部加粗），但不包含 Word/LibreOffice 的全部字距、表格单元格与字体回退规则，因此不承诺测量与实际 PDF 百分之百一致，也不承诺微调调用在 500ms 内完成。求职信在无已验证公司背景时使用 `jd_only` 策略并阻断可识别的公司动态断言；这不是通用事实验证器。

设置 `CAREER_SKILL_VERIFIED_CACHE_DIR` 可选用私有 SHA-256 缓存；它依据原子经历、完整 Master CV、JD 分析及布局快照生成键，**只存最终 PDF 终验成功的载荷**。缓存目录包含个人履历文本，请放在仅本人可访问的磁盘；默认不持久化。不同 JD、证据或布局不会因同一岗位原型而直接复用：未经验证的向量聚类相似度不是安全的事实等价条件。

将 `CAREER_SKILL_MASTER_CV_PATH` 指向自己控制的私有 JSON 文件后，可调用 MCP `append_experience(section_type, title, source_bullets, metrics, tools)`。新增工具/指标必须存在于提供的原始事实 bullet 中；修改前会将完整旧版存到同目录的 `<CV 文件名>.history/`，`cv://master_cv.json` 下次读取即反映更新，Fact Cards 由它派生而不维护第二套事实。该步骤不能独立证明用户输入为真，需要本人审核，不要将个人文件或历史快照提交到公共仓库。完成 PDF/质检的投递自动在忽略的 `output/.career_ledger.json` 中记录公司、JD 关键词、PDF SHA-256、ATS 启发式分数与 Tier 1 ID；dry-run 或失败不入账。

原模板 DOCX 工具可传 `resume_language="zh_CN"` 生成有来源 ID 和原始指标约束的中文技术简历，且必须配置模型。中文正文复用原 DOCX 字体/容器和 PDF 终验；求职信仍是现有英文 LaTeX 模板，并未声称提供中文求职信。用 `python -m pytest tests/test_golden_applications.py -q` 可用三类**合成** JD 对单页、证据召回和求职信三段结构做完整离线回归；这些测试不会调用 DeepSeek，不是模型生成质量的金标准。

## MCP Resources 与 Prompts

- `cv://master_cv.json`：默认是空白模板；仅设置 `CAREER_SKILL_MASTER_CV_PATH` 后才读取指定个人简历。
- `config://archetypes.json`：岗位术语词典和证据约束。
- `templates://styles.json`：可用 LaTeX 样式和 DOCX 几何策略元数据。
- `workflow_full_tailoring`：JD 分析、布局预算、payload 生成、原位注入和 PDF 验证的执行顺序。
- `workflow_quick_audit`：只诊断证据匹配与缺口，不生成文件。

本地客户端默认使用 stdio。容器/HTTP 部署可显式设置 `CAREER_SKILL_MCP_TRANSPORT=streamable-http`、`CAREER_SKILL_MCP_HOST` 和 `CAREER_SKILL_MCP_PORT`；不要在没有认证或受控反向代理的情况下把 MCP HTTP 端口暴露到公网。

## 安装

要求 Python 3.11+，并安装兼容 `fontspec` 的 `tectonic`、`xelatex` 或 `lualatex`。只安装 `pdflatex` 不足以编译本项目模板。Windows 当前 winget 源可直接安装 MiKTeX：

```powershell
winget install --id MiKTeX.MiKTeX -e --scope user
```

安装后重新打开终端并验证：

```powershell
xelatex --version
```

如果 winget 中没有 Tectonic，可用 PowerShell 从官方 GitHub Release 下载 Windows x64 版本；项目会自动识别 `.tools\tectonic\tectonic.exe`：

```powershell
$ErrorActionPreference = "Stop"
$tools = Join-Path (Get-Location) ".tools\tectonic"
New-Item -ItemType Directory -Force $tools | Out-Null
$release = Invoke-RestMethod `
	-Uri "https://api.github.com/repos/tectonic-typesetting/tectonic/releases/latest" `
	-Headers @{ "User-Agent" = "CareerResumeSkill" }
$asset = $release.assets | Where-Object {
	$_.name -match "x86_64-pc-windows-msvc\.zip$"
} | Select-Object -First 1
$zip = Join-Path $env:TEMP $asset.name
Invoke-WebRequest $asset.browser_download_url -OutFile $zip
Expand-Archive $zip -DestinationPath $tools -Force
Remove-Item $zip -Force
.".tools\tectonic\tectonic.exe" --version
```

`.tools/` 已加入 `.gitignore`，不会把本地编译器提交到仓库。

### 本机网页向导（Windows）

双击仓库根目录的 `start_career_resume_web.bat`。首次启动会创建项目虚拟环境并安装 Python 依赖，随后自动打开本机网页；之后再次双击即可使用。默认端口为 `8765`，若被占用会自动保留下一个可用的本机端口并打开对应页面。网页仅绑定 `127.0.0.1`，不会向局域网开放。API Key 可在表单中临时输入，也可使用本机 `.env` 中已配置的 Key；表单 Key 不写入文件、浏览器存储或 URL。简历原件在生成期间放入临时目录，生成文件保存在本机 `output/web/`。LaTeX PDF 需要 Tectonic/XeLaTeX/LuaLaTeX；DOCX 转 PDF 需要 Word 或 LibreOffice，网页会报告环境错误但不会绕过质量门禁。生成报告含仅由阶段名和秒数组成的 `performance` 诊断，不含简历、JD、Key 或模型响应。

当前网页模式由 DeepSeek API（或 `.env` 中配置的 OpenAI-compatible 服务）执行模型生成。仅向 AI 上传 `SKILL.md` 不会让 MCP 后端自动使用该 AI 客户端自己的模型；如需此模式，仍需在支持 MCP 的 AI 客户端连接本项目 MCP Server。现有 MCP 与 CLI 路径保持可用。

运行时依赖可通过 `python -m pip install -r requirements.txt` 安装；开发环境（含 pytest 和 Ruff）使用 `python -m pip install -r requirements-dev.txt`。两个 requirements 文件都转交给 `pyproject.toml` 的依赖/extra 声明，避免维护重复或过期的包列表。也可以直接使用 pip extra 安装开发依赖：

```powershell
python -m pip install -r requirements-dev.txt
# .env 已存在时只需编辑它；若被删除，可重新复制示例：
Copy-Item .env.example .env
```

Python 依赖包含 Pillow（字体物理宽度估算）、`python-docx`、Pydantic、MCP、DeepSeek OpenAI-compatible client 和 LaTeX PDF 工具。表格段落优先读取 `tcW` 和 gridCol；缺失宽度时按当前行单元格数等分并标记风险。复杂 Word 布局仍以实际 PDF 渲染为准。DOCX → PDF 还需要单独安装 LibreOffice：

```powershell
winget install --id TheDocumentFoundation.LibreOffice -e
```

当前 winget 包是 x64 MSI，不要添加 `--scope user`；安装时可能需要管理员权限。若 winget 仍失败，可使用官方 MSI：

```powershell
$msi = Join-Path $env:TEMP "LibreOffice_26.8.0_Win_x86-64.msi"
Invoke-WebRequest `
	"https://download.documentfoundation.org/libreoffice/stable/26.8.0/win/x86_64/LibreOffice_26.8.0_Win_x86-64.msi" `
	-OutFile $msi
Start-Process msiexec.exe -ArgumentList "/i `"$msi`"" -Wait
```

DOCX 转 PDF 会优先使用 Microsoft Word；Word COM 失败或超时且 LibreOffice 已安装时会自动回退，并清理失败导出的中间 PDF。`CAREER_SKILL_WORD_CONVERSION_TIMEOUT_SECONDS` 默认 60 秒，可在 `.env` 中设为 1–180 秒。默认使用 `deepseek-chat` 和 `https://api.deepseek.com`。本地 vLLM 或其他 OpenAI-compatible DeepSeek 服务可通过 `.env` 中的 `DEEPSEEK_BASE_URL` 与 `DEEPSEEK_MODEL` 切换。`.env` 留空时所有流程自动使用离线 fallback。

### Docker

仓库 Dockerfile 提供 LibreOffice、TeX 和 Liberation/Carlito/DejaVu/Noto CJK 字体栈。构建上下文会排除 `.env`、本地简历、测试文件和输出目录：

```powershell
docker build -t career-resume-skill .
docker run --rm -p 8000:8000 `
	-e DEEPSEEK_API_KEY `
	-v "${PWD}/output:/app/output" `
	career-resume-skill
```

容器默认使用 `streamable-http` 并绑定 `0.0.0.0`；本地 Docker 映射仍应只开放给可信客户端。若要启用 CV Resource，可将个人文件只读挂载到容器，并设置 `CAREER_SKILL_MASTER_CV_PATH` 为容器内路径。

## MCP 客户端配置

完成 editable install 后，将以下 server 加入 MCP 客户端配置：

```json
{
	"servers": {
		"career-resume-skill": {
			"type": "stdio",
			"command": "python",
			"args": ["-m", "career_resume_skill.server"],
			"env": {
				"DEEPSEEK_MODEL": "deepseek-chat",
				"CAREER_SKILL_OUTPUT_DIR": "output"
			}
		}
	}
}
```

也可以直接启动：

```powershell
python -m career_resume_skill.server
```

CLI 输出目录可用 `--output-dir` 固定；未传入时读取 `.env` 的 `CAREER_SKILL_OUTPUT_DIR`，默认是工作区下的 `output`。LaTeX 申请包会在该目录下创建独立的时间戳 run 目录，默认结构化报告固定为 `<output-dir>/application_package.json`；DOCX 使用 `--output-docx` 指定文件名时，若文件名是相对路径且传入了 `--output-dir`，也会写入该目录。

一键生成完整申请包：

```powershell
python -m career_resume_skill.cli `
	--jd "https://company.example/jobs/123" `
	--cv examples/master_cv.json `
	--company "Target Company" `
	--output-dir output/deliveries `
	--report output/application_package.json
```

未安装 TeX 或需要先审核内容时加 `--dry-run`。URL 抓取仅允许公网 HTTP(S)，每次重定向重新校验并固定目标 IP，同时限制跳转次数、内容类型和 2 MiB 响应大小；受反爬保护的页面应改用复制后的 JD 文本或 `--jd-file`。

使用原始 Word 模板执行 Track A 时，指定 `--track docx`、模板和输出路径；可用 `--date` 固定求职信日期：

```powershell
python -m career_resume_skill.cli `
	--track docx `
	--docx-template examples/resume.docx `
	--output-docx output/tailored.docx `
	--jd-file input/job-description.txt `
	--company "Target Company" `
	--date 2026-09-27
```

不启动 MCP、也不需要 JD/简历输入时，可直接诊断本机环境：

```powershell
python -m career_resume_skill.cli --doctor
```

`--doctor` 默认输出单行 JSON，适合 PowerShell 重定向或保存；需要人类可读格式时使用 `--pretty-doctor`。不要用 `Select-Object -First` 截断外部 Python 进程的 stdout，否则 PowerShell 可能将被截断的进程显示为 `-1`。

## Master CV

[examples/master_cv.template.json](examples/master_cv.template.json) 是不含候选人事实的填写模板；[examples/master_cv.json](examples/master_cv.json) 仅用于自动化测试，不能直接用于真实投递。建议把所有真实项目、研究、工作、竞赛、论文和技能都保存在 Master CV 中；模型只负责选择、排序和忠实改写。完整规则见 [docs/master-cv.md](docs/master-cv.md)。核心字段为：

```text
name, contact, profile, sections[].{type,title,items[]}, skills
items[].{title,organization,location,dates,bullets[]}
```

## 使用顺序

1. 用完整 JD 文本或公网 URL 调用 `analyze_job_description`。
2. 把完整 Master CV 和分析结果传给 `tailor_resume_content`。
3. 检查 `gap_analysis` 与 `evidence_gaps`，必要时补充真实证据后重新生成。
4. 调用 `draft_cover_letter`；需要公司定制时传入已核验的公司背景。
5. 给渲染 payload 补齐 `name`、`company_name`、`date` 和 `contact`。
6. 分别以 `resume`、`cover_letter` 调用 `render_and_compile_latex`。

也可直接调用 `generate_application_package` 完成全部步骤。每次申请包都会返回唯一的 `run_id` 和 `run_dir`，PDF/LaTeX 产物写入独立目录，不会覆盖之前的投递版本。DOCX Track 的 `output_docx` 和同名 PDF 是权威 Golden Artifact；目录中不会保留 compact 中间候选。报告中的 `quality_report.typography_audit` 会记录 `final_page_count`、`applied_compact_level`、`line_spacing_twips`、`margins_adjusted`、`heading_protection_relaxed`、Cover Letter 词数和 `visual_density_score`。只有 `verified=true` 才表示最终 PDF 通过单页、指标、技术来源、黑名单、标点和字形门禁，且 Resume/Cover Letter 内容 Critic 全部通过；失败结果仅供检查，不写入投递 Ledger。

路径说明：`.env` 中的 `CAREER_SKILL_OUTPUT_DIR` 会在配置加载时解析为绝对路径；CLI 报告、DOCX 资源、manifest、LaTeX 和 PDF 路径也会返回绝对路径，避免从不同工作目录启动时产物散落。

## 验证

```powershell
python -m pytest -q
python -m ruff check src tests
```

核心文件：

```text
src/career_resume_skill/
├── facts.py                         # 事实、指标与技术词抽取；加载技术词表和黑名单
├── hallucination_blacklist.json     # 高危技术/业绩术语，必须有源证据才能使用
├── text_utils.py                    # 共享中英文句末标点规范化
└── templates/                       # 受控 LaTeX 简历与 Cover Letter 模板
```

Skill 的代理行为规则见 [SKILL.md](SKILL.md)，系统边界见 [docs/architecture.md](docs/architecture.md)，中文架构介绍见 [docs/architecture.zh-CN.md](docs/architecture.zh-CN.md)。

结构化 Master CV 使用本项目受控的单栏 A4 `resume.tex.j2`：三档边距/行距/列表间距宏先尝试不改内容的 PDF 编译，超页后才由 Python 记录并裁剪低优先级经历；紧凑档不会悄悄略过第 4 条 bullet。`cover_letter.tex.j2` 为独立 A4 商务信件：居中的联系块、日期、招聘组及显式传入的公司名称，随后是已验证的三段正文。没有证据的部门、收件人、城市不自动补写。所有输入值通过统一 LaTeX 转义；模板和 PDF 的实际页数/可提取文本均有回归测试。目标是可审计的文本流，不承诺某一家商业 ATS 的解析通过率，也不按固定字数保证视觉占比。

## DOCX 原地回填

先调用 `inspect_docx_layout` 获取 `paragraphs[].node_id`、run 样式、表格路径和图片资源；再把需要修改的 paragraph ID 映射到新文本，调用 `inject_docx_layout`。默认用源字体与页宽/单元格宽度估算折行，最多允许原文行数和两行中的较大者，不使用字符比例。清理 tab 时保留原段落样式及对齐；未修改的 ZIP entry 仍原样复制。

DOCX → PDF 需要安装 LibreOffice，并确保 `soffice` 或 `libreoffice` 在 PATH 中；没有 LibreOffice 时仍可生成和回填 DOCX，但转换工具会返回明确错误。

完整 DOCX 参数、JSON 示例和保真边界见 [docs/docx.md](docs/docx.md)。

当输入是 DOCX 时，使用 `generate_docx_application_package` 会强制进入原模板回填管线，不调用默认 LaTeX Resume 模板。正文 Bullet 不做字符 padding 或机械截断；版式安全由动态段落数量、原样式克隆和最终单页质量门禁共同控制。

DOCX 原模板采用动态金字塔预算：按 JD 相关度把有证据的经历分为 Tier 1（3--4 条）、Tier 2（2 条）和 Tier 3（1 条），整份经历区最多 11 条。引擎会克隆已有 Bullet paragraph 的完整 OOXML 样式或移除多余段落，最终 PDF 页数仍由单页质量门禁检查。

也可以不启动 MCP，直接使用独立 DOCX CLI：

```powershell
career-resume-docx inspect master.docx --manifest output/layout.json
career-resume-docx audit master.docx
career-resume-docx inject master.docx output/tailored.docx --replacements output/replacements.json
career-resume-docx convert output/tailored.docx --output-dir output/pdf
```

`audit` 无需 JD、模型或 PDF 编译。Fact Cards 与 PDF 完整性门禁会将 `sub-10ms`、`10⁶`、`1e-6` 作为完整指标，不会把指数部分拆成另一项数字。

如果命令尚未进入当前 PATH，可使用模块形式：

```powershell
python -m career_resume_skill.docx_cli --help
```

遇到安装或运行问题时，先调用 `check_environment` 或执行 `python -m career_resume_skill.cli --doctor`。它会报告 `DEEPSEEK_API_KEY` 是否已配置、项目内 Tectonic 是否可用、Windows 默认路径下是否存在 LibreOffice、关键 Python 依赖版本及输出目录可写性；不会显示密钥值。
