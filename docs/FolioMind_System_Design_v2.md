# FolioMind 系统设计 v2：AI 课程资料理解与组织

更新日期：2026-11-08。状态：需求与设计草案，未完成实现与效果验证。
本版依据本轮明确确认的方向更新同一份系统设计。下文正文为当前范围；附录保留原 v1 全文，仅作历史记录，其中“全部功能均进入首版”等旧表述不再作为当前首版承诺。

## 1. 项目定位与目标

FolioMind 是面向学生的 Windows 桌面 AI 课程资料理解与组织助手。用户导入名称杂乱、内容混合的课程资料，AI 根据正文识别主题与用途，综合提出按“课程／用途”组织的两级分类方案，并给出可定位的正文依据。用户以文字或手动方式修改，查看差异并确认后保存；实际移动和改名另行确认。

主要难题是“不清楚资料讲什么以及如何组织”，文件操作是交付结果的辅助能力。AI 的效果要通过对照实验验证，不以模型调用数量、聊天框或功能数量作为价值证明。

## 2. 本轮确认的核心规则

| 决策 | 当前规则 |
| --- | --- |
| 演示场景 | 混乱课程资料整理 |
| 课程来源 | 用户可提供课程清单，也可让 AI 推断；无法确定时不强行指定 |
| 默认分类 | 一级按课程，二级按课件、学习笔记、实验报告等用途；最多两级 |
| 文件归属 | 一个主分类；跨课程时建议一个主课程，其他课程作为标签，并标记供审核 |
| 不确定文件 | 留在待确认，展示候选课程和真实依据，不阻塞整批分析 |
| 修订入口 | 支持文字要求与手动编辑 |
| 修订应用 | 先展示修改前后差异，用户确认后应用 |
| 依据 | 分类理由＋可定位的原文片段；生成理由本身不能充当原文 |
| 批量审核 | 按建议类别分组，可展开单文件；分类、标签、拟用名称分别接受 |
| 保留用户决定 | 重新分析不覆盖已确认归属，产生新建议；方案修订亦需确认 |
| 云端分析 | 用户配置自己的 API Key 和服务地址；主动启动，每批确认发送范围 |
| 文档处理 | TXT、MD、DOCX、文字型 PDF；长文分段后综合，展示实际覆盖；无 OCR |
| 文件执行 | 原位管理或实际整理均可；预览确认后本地程序执行，不授予模型任意操作能力 |

若用户提供课程清单，清单作为优先候选和上下文；文档可能不在清单内，AI 可提出新课程候选，但不得未经用户确认建立已接受归属。该处理为本版设计默认值，需在原型中展示。

## 3. 当前首版与后续范围

| 级别 | 功能 | 范围 |
| --- | --- | --- |
| 首版核心 | 单篇理解 | 主题、用途、简短摘要、标签、名称建议、候选课程、正文依据和覆盖状态 |
| 首版核心 | 整批组织 | 综合各篇分析，提出课程及用途结构；归纳整体逻辑，检查同义类别和不一致归属 |
| 首版核心 | 歧义审核 | 待确认队列、跨课程提示、候选依据；可手动归类 |
| 首版核心 | 文字修订 | 理解分类要求，生成可校验的变更提案，展示差异，确认后应用 |
| 首版支撑 | 导入与读取 | 文件夹、多个文件、拖入；递归可选、目录排除、手动刷新、状态和取消 |
| 首版支撑 | 基础管理 | 单一默认资料空间；两级分类与普通标签编辑；正文、摘要及证据定位 |
| 首版支撑 | 基础检索 | 名称、正文、分类、标签；类型、分类、标签筛选；真实命中片段 |
| 首版交付 | 整理与改名 | 原目录或指定目标、分类路径、独立改名、同名跳过或已确认编号、逐项记录与按批条件性撤销 |
| 后续增强 | AI 辅助查找 | 主动启用，将模糊描述转成可编辑条件；先验证实际收益 |
| 后续增强 | 复杂管理 | 多空间、跨空间转移、多套可复用分类方案、标签组与标签合并 |
| 待验证 | 向量检索 | 基于测试结果决定，不是 AI 理解和整批组织的前置条件 |
| 暂不包含 | OCR、问答、重复检测、自动监听、暂停续传、原排版预览 | 不为突出 AI 增添无关能力 |

“单一默认资料空间”等收缩是本次授权方向下的实现默认值；保留数据模型未来扩展能力，不在当前界面开发多空间功能。
支持用户编辑当前方案，或提供课程清单及已有两级结构作为约束，不要求先实现完整方案库。
首版交付物仍包含安全的实际整理；开发 AI 核心原型时暂不移动文件，先证明建议效果。

## 4. AI 核心流程与本地程序分工

1. 导入与解析：本地程序提取标题、段落、表格及可用文字，建立稳定段落/页码定位和内容版本。提取失败、扫描型 PDF、部分可读分别显示。
2. 准备分析：用户可提供课程清单或当前结构；程序划分片段，展示待发送文件、片段范围、模型和分析目标。确认后执行。
3. 单篇理解：按片段理解主题、用途和依据，再综合文档级结果；不把只看开头视为全文分析。
4. 整批归纳：基于文档级分析与已验证证据，归并候选课程、统一用途名称并分配建议归属。批量过大时分批归纳再做全局一致性检查，不能简单拼接所有正文到一次请求。
5. 方案检查：程序校验文件集合、分类层级、引用、重复归属、证据定位与覆盖状态；无效项进入错误或待确认，不直接入库为已确认分类。
6. 人工审核：按课程/用途树查看，点选文件可看到理由和原文；不确定文件集中展示。
7. 方案修订：用户文字要求或手动编辑 → 变更提案 → 逐项差异 → 用户确认 → 生成新方案版本；不移动磁盘文件。
8. 保存与整理：接受分类、标签和拟用名称；另建实际操作计划，预览确认后由本地程序执行。

AI 负责语义分析、跨文档归纳和文字要求解释。本地程序负责扫描、解析、索引、对象与证据校验、版本控制、差异计算、数据库写入和真实文件操作。
文档内容视为待分析材料，内容中的命令不得改变发送范围、方案权限或执行流程。

## 5. 页面与交互调整

默认仍进入文件库，以课程分类树为主导航。无需新增数据看板或通用聊天首页。

| 页面/区域 | 当前设计 |
| --- | --- |
| 导入与分析面板 | 来源、递归/排除、可选课程清单、使用已有结构或允许建议新结构、发送范围确认 |
| 文件库 | 左侧课程/用途树和待确认队列，中间文件列表，右侧正文、摘要、标签与依据 |
| AI 方案审核 | 类别树、归纳说明、各组文件、候选归属；分类/标签/名称分项批量接受 |
| 方案调整区域 | 当前方案旁的文字输入，仅针对该方案；显示本次要求及解释 |
| 差异预览 | 新增/删除/重命名类别、文件归属变化、标签和拟用名称变化；未改项目折叠 |
| 整理计划 | 实际源目标路径、改名、冲突、确认与执行结果 |
| 操作历史/设置 | 按批撤销、云端配置与连接测试；任务区提供进度和取消 |

文字指令示例：“笔记和复习提纲合并，实验报告保留”。这里合并的是分类方案中的类别建议，区别于后置的专用标签管理功能。
若要求与两级层级约束冲突，展示限制和可选修改，不静默放宽层级。
AI 对某要求无法解释时，请求澄清并保留当前版本；不得假装已完成。

## 6. 数据模型更新

继承历史版 files、documents、categories、file_classifications、tags、file_tags、ai_profiles、tasks、consents、operation_batches/items/events 等基础对象。当前界面仅使用一个默认 workspace；多空间相关服务暂不实现。
旧 ai_suggestions 可保存原始建议，但当前归属的变更以有版本的 proposal 为审核单位，不同时维护两套可相互覆盖的写入口。

| 新增/调整对象 | 核心字段 | 约束 |
| --- | --- | --- |
| course_inputs | id, workspace_id, input_revision, course_items, supplied_by_user | 记录可选用户课程清单与别名，不将 AI 猜测写成用户输入 |
| document_segments | id, file_id, content_version, locator, text, extraction_quality | locator 为 PDF 页码/块、DOCX 段落/表格单元格、TXT/MD 行号；表征提取文本而非保证版式 |
| document_analyses | id, file_id, content_version, job_id, topic, purpose, summary, candidate_courses, tags, proposed_name, coverage, status | 与内容版本绑定；未知用途和课程保留不确定原因 |
| analysis_evidence | id, analysis_id, segment_id, start_offset, end_offset, quote, claim_kind | 引用必须属于对应版本且可定位；程序核对文字，不能仅保存模型编造引用 |
| organization_runs | id, file_snapshot, course_input_revision, constraints, job_id, coverage, status | 固定本批允许文件与课程约束；包含成功/失败/未覆盖列表 |
| organization_proposals | id, run_id, revision, base_revision, structure, assignments, rationale, state | 草案不修改已确认 categories；全部 assignments 引用合法文件；一级课程二级用途 |
| proposal_assignment_reviews | proposal_id, file_id, aspect, decision, edited_value | aspect 为 classification/tags/name；逐项保存用户选择，支持批量 |
| revision_requests | id, proposal_id, base_revision, source, instruction, structured_changes, status | source=text/manual；模型仅提出允许的结构化变更 |
| proposal_diffs | id, request_id, base_revision, candidate_revision, normalized_diff, state | 差异由程序从两个快照计算，不依赖模型口述；过时基线禁止直接应用 |
| proposal_applications | id, proposal_id, revision, accepted_aspects, applied_at | 应用后事务更新已确认分类、标签、拟用名称；实际路径仍不变 |

状态：proposal 为 draft/ready/partially_applied/applied/superseded/stale；revision_request 为 pending/needs_clarification/ready/confirmed/rejected/failed。
每个方案修订产生候选新版本；确认后才替换当前草案。已保存分类不会因新草案自动覆盖。
文件内容或课程约束变化后标记受影响分析与方案过时；需要重新分析或再次确认，不能将旧证据展示为新内容依据。
删除方案类别时，必须为所有受影响文件提供新归属或待确认；删除草案类别不直接删除磁盘目录。

## 7. 本地服务接口更新

| 服务接口草案 | 输入/输出与规则 |
| --- | --- |
| DocumentService.extract(files) -> TaskId | 返回正文、片段定位、覆盖与状态，保留已确认范围 |
| AnalysisService.prepare(file_ids, course_input_revision) -> TransmissionPreview | 固定内容版本、单篇和批量归纳阶段的数据范围 |
| AnalysisService.run(preview_id, consent_id) -> TaskId | 分段理解、文档综合和证据校验；输出 DocumentAnalysis |
| OrganizationService.generate(run_id, constraints) -> TaskId | 基于成功分析提出方案，对失败文件列出原因，不宣称整批完整理解 |
| ProposalService.get(proposal_id, revision) -> ProposalView | 类别树、归属、依据、待确认项与分析覆盖 |
| RevisionService.prepare(proposal_id, base_revision, instruction) -> TransmissionPreview | 预览修订需要发送的要求、方案及最少必要上下文 |
| RevisionService.propose(preview_id, consent_id) -> TaskId | 返回受限 ChangeSet；请求补充正文必须另行纳入发送范围 |
| RevisionService.preview_manual(proposal_id, base_revision, edits) -> ProposalDiff | 手动编辑也使用同一校验与版本流程，不调用模型 |
| RevisionService.confirm(diff_id, base_revision) -> ProposalRevision | 检查基线未变化，应用到当前草案，保留历史快照 |
| ReviewService.apply(proposal_id, revision, selections) -> ApplyResult | 分别接受分类、标签和名称；校验内容版本，事务保存，不改磁盘 |
| OperationService.build/confirm/execute/preview_undo/undo | 延续历史版固定计划、禁止覆盖、逐项日志和条件性撤销约束 |
| SearchService.search(query, filters) -> SearchHits | 本地全文检索；AI 辅助查询为后续扩展，不绑定为搜索前置 |

ChangeSet 仅允许：新增/重命名/删除草案类别、将文件设为待确认或分配到已有/新候选类、标签及拟用名称建议。模型不得提交绝对执行路径、Shell、SQL 或任意代码。
分类/标签/名称的确认各自独立，跨项引用失效时提示用户修复。类别关系及文件归属修改不得越过两级和唯一主分类约束。

## 8. 证据、长文与云端范围

- 证据是否能精确匹配只能证明引用存在，不能证明推理正确；界面保留原文和上下文供用户核对。
- 课程归属可能是从主题推断，而文档并未写课程名，应标记为推断依据，不能将相关主题当作确切课程名称证明。
- 分段分析后综合要保存实际处理的片段列表；中间失败、不足的文字层或只覆盖部分页需可见，不能伪称完整阅读。
- 整批归纳只提供已允许发送的摘要、分析和证据；如需补充正文，必须在原确认范围内，否则重新预览并确认。
- 修订请求本身可能包含用户隐私。沿用每批确认规则，首次发送修订要求时展示相应范围；手动修改不需云端。
- 不以未校准百分比展示置信度；用“候选、待确认、覆盖不足”等可核验状态。
- 密钥使用系统凭据存储候选方案，具体实现待验证；日志不记录密钥和完整正文。
- 取消保留已完成结果；网络失败不影响原文件和既有已确认分类。

## 9. 新开发顺序及验收

本轮重新排序，优先完成可证明 AI 价值的端到端流程。旧 M0-M9 顺序仅为历史。

| 阶段 | 交付 | 主要验收 |
| --- | --- | --- |
| N0 场景样本与验证标准 | 多课程、混合用途、名称含糊、跨课程、未知课程和长文样本；人工参考与规则基线 | 样本来源可说明；真实材料与构造材料区分；不提前声称 AI 更优 |
| N1 内容与证据基础 | 四格式解析、稳定段落/页码定位、内容版本、覆盖与失败状态；最小桌面文件列表 | 已有文字准确定位；扫描 PDF 不当有效正文；失败不阻塞其他文件 |
| N2 单篇 AI 理解 | 用户 Key、发送确认、分段综合、结构化输出和证据核对 | 不支持/失败/长文缺段明确；摘要与分类理由可核对；名称仅建议 |
| N3 整批分类方案 | 可选课程清单、课程/用途两级树、分组审核、待确认与跨课程标签 | 文件无重复主归属；陌生课程不硬猜；相同课程称谓可归并；保留已确认信息 |
| N4 修订与差异 | 文字要求、手动编辑、版本快照、真实差异、分项确认 | “合并笔记和复习提纲”等要求可见具体变化；非法层级拒绝；旧基线不能覆盖新方案 |
| N5 原位可用版本 | 保存分类/标签/拟用名称，文件库、基础全文搜索、刷新、忽略恢复、任务取消 | 用户不移动文件即可完成整理与查找；正文变化使旧依据过时 |
| N6 实际整理交付 | 移动、独立改名、冲突、日志、撤销、桌面打包 | 预览和执行一致；不覆盖；中断可核对；条件性按批恢复；无云端也能浏览既有结果 |
| N7 效果对照与答辩 | 同批数据规则基线与 AI 对照、错误案例、资源耗时和演示 | 报告实际结果与限制；不把原型已有说明当已实现证明 |

基础存储与后台任务随 N1/N2 建立；中文全文索引在 N5 交付，单独做兼容验证，不阻塞 N2-N4。GUI 框架、解析器、索引、云端模型和打包工具在进入实现前根据官方资料及样本测试确定。

## 10. AI 价值验证方案

规则基线：文件名/提取正文关键词与用途规则，使用明确配置的课程关键词，不使用大模型。AI 方案与基线使用同一批文档及相同可用课程清单，不能只给 AI 更充分的输入后声称优越。

| 指标 | 记录方法 |
| --- | --- |
| 主课程与用途合理性 | 分别人工核对；课程未知时允许待确认；跨课程资料保留可接受候选范围，不强制唯一标准答案 |
| 人工修改量 | 统计需要改动的文件数、类别数及总文件数；分别记录基线和 AI |
| 不确定处理 | 记录正确保留待确认、错误硬归类、过度待确认的数量 |
| 依据质量 | 核对定位有效、引用真实、与分类理由相关三个维度 |
| 文字修订效果 | 预设明确要求，检查应改文件、未要求文件和层级约束；记录误改与未改 |
| 使用成本 | 记录耗时、调用次数、可获得的 token/费用数据及失败；缺失数据不得伪造 |
| 用户体验 | 同一任务对照记录完成时间与修改步骤；正式用户研究需要真实参与记录 |

先在开发样本调整规则/提示，再用保留样本评估，避免反复调试同一批后把结果当泛化能力。所有指标先定义再测试；本文不填造准确率或“提升百分比”。

## 11. 当前设计与历史方案关系

当前首版以本版第 3 节为范围，以 N0-N7 为开发顺序。多空间、跨空间与复杂标签等保留为后续功能；原位管理与审核后实际整理仍保留。
README 尚未随本次更新同步，也没有向 GitHub 提交。本文件记录需求与设计，不是已完成产品说明。
本轮无需继续扩充功能，下一步准备课程资料样本并验证“单篇理解—整批方案—文字修订”的可运行原型。

---

# 附录：v1 历史设计全文（非当前首版范围）

以下完整保留调整前设计，用于追溯原功能决策；与正文冲突时，以正文为准。

# FolioMind 首版系统设计草案

日期：2026-11-08。依据：本轮对话逐项确认的功能与交互。本文为设计交付，不代表代码已实现，也未重新核验参考仓库。开发任务为里程碑级拆分，进入某个里程碑前再编写具体实现计划。

## 1. 已确定范围

- Windows 桌面客户端；支持 TXT、MD、DOCX、文字型 PDF，不含 OCR。
- 命名管理空间可包含多个来源；一个文件仅属于一个空间。同一路径重复添加复用记录；跨空间添加提示取消或转移。
- 手动刷新，仅更新新增或变化文件；包含子目录可选，支持排除目录。移除管理记录保留原文件并记住忽略状态，可恢复。
- 每个空间使用一套分类方案，可保存多套方案；最多两级分类，一个文件一个主分类、多个标签。一级类别浏览包括下级文件。
- 分类支持系统提出方案或用户提供结构；新增、删除、改名类别及批量调整归属。删除类别可选择转入其他类别或待分类。首版不提供专用类别合并/拆分操作。
- 标签支持手动/批量增删、改名、合并、分组。
- 用户提供云端 API Key 与服务地址；仅主动分析全部或选中文件。每批发送前确认文件及内容范围。长文分段后综合，展示实际覆盖范围。
- 每次文档 AI 分析生成分类、标签、简短摘要及名称建议；各类建议分别接受，可批量操作。保留已确认分类，新建议独立展示。
- 默认本地全文与条件检索；按类型、分类、标签筛选。主动启用 AI 辅助查找，展示可修改的查询条件；是否引入向量检索待验证。
- 显示提取正文、基本信息、摘要和标签；原文件由外部软件打开，不承诺还原原始排版。
- 原位管理与实际整理均支持；原目录内或另选目标目录，按主分类层级生成路径。可独立改名。执行前预览、确认，同名默认跳过，可逐项选择添加编号。
- 历史可按批次条件性撤销；扫描、解析、AI 分析显示进度并支持取消。首版不包含暂停续传、专用失败重试入口、重复文件检测。

## 2. 页面与流程

默认进入文件库：左侧空间/分类/标签，中间文件列表与搜索，右侧正文和详情。其他入口为建议审核、整理计划、操作历史、设置；底部任务区显示进度和取消。

1. 添加：选择空间及来源 → 配置递归/排除 → 本地扫描解析 → 保存内容并建立索引 → 展示状态。不会自动调用云端或移动文件。
2. AI 分析：选择范围及分类方式 → 预计算分段与发送范围 → 用户确认 → 调用云端 → 校验并保存建议 → 按建议类别分组审核。
3. 审核：分类、标签、拟用名称可分别批量接受；摘要标记生成内容。接受拟用名称仅保存计划值，不修改磁盘。
4. 搜索：输入关键词 → 本地检索；或主动 AI 辅助 → 确认发送查询范围 → 展示解析条件 → 用户修改并检索 → 真实命中片段。
5. 整理：选中文件 → 选择原位改名或移动目标 → 生成逐项计划 → 处理冲突 → 确认冻结计划 → 执行前复核 → 逐项记录结果。
6. 撤销：选择历史批次 → 检查当前状态并预览 → 确认 → 按逆序恢复可恢复项 → 报告成功/失败/跳过。

## 3. 模块边界与代码布局建议

采用单机桌面架构；GUI 调用本地应用服务，耗时任务在后台执行。模块接口为进程内方法，不需要为课设额外部署 HTTP 业务服务器。

| 建议目录 | 职责 |
| --- | --- |
| src/foliomind/ui/ | 页面、交互、状态展示；不直接执行文件操作或调用云端 |
| src/foliomind/workspaces/ | 空间、来源、排除与忽略、跨空间转移 |
| src/foliomind/documents/ | 扫描、各格式解析、内容版本与变化识别 |
| src/foliomind/catalog/ | 分类方案、文件归属、标签及合并 |
| src/foliomind/search/ | 查询条件校验、全文索引、排序与命中片段 |
| src/foliomind/ai/ | 服务适配、发送范围、分段综合、输出校验和建议审核 |
| src/foliomind/operations/ | 整理计划、预检、执行日志与撤销 |
| src/foliomind/tasks/ | 后台任务、进度事件与协作取消 |
| src/foliomind/storage/ | 数据库连接、迁移和事务 |
| tests/ | 业务约束、解析样本、搜索和文件操作验证 |

候选技术：沿用 Python 核心方向，桌面 GUI、SQLite 本地存储、中文全文索引及各格式解析器进入技术验证。本文不锁定框架、库版本、模型或云端供应商；选型前查阅官方文档并验证授权与兼容性。

## 4. 数据表设计

以下类型为逻辑类型，ID 为应用生成的不透明标识；时间统一保存带时区时间。外键、唯一约束和业务校验共同维持一致性。

| 表 | 核心字段 | 约束与用途 |
| --- | --- | --- |
| classification_schemes | id, name, revision | 保存可复用分类方案 |
| categories | id, scheme_id, parent_id, name, sort_order | 最多两级；同方案同父级名称唯一，根类别也需唯一；禁止循环 |
| workspaces | id, name, scheme_id | 每个空间一套方案 |
| sources | id, workspace_id, kind, path, canonical_path, recursive, enabled | kind 为 directory/file；来源不代表文件已复制 |
| exclusions | id, source_id, pattern, kind | 读取正文前应用排除规则 |
| files | id, workspace_id, current_path, canonical_path, size, modified_at, content_hash, content_version, parse_status, availability, extraction_quality | canonical_path 全局唯一；路径可更新，不作为永久 ID |
| file_sources | file_id, source_id, discovered_at | 复合唯一；同一空间内重叠来源不创建重复文件 |
| documents | file_id, content_version, text, coverage, parser_name, error_code | 文件和内容版本复合唯一；正文与覆盖信息；首版可仅保留当前正文 |
| file_classifications | file_id, category_id, confirmed_at | file_id 唯一；无关联即待分类；类别必须属于该空间方案 |
| tag_groups | id, workspace_id, name | 首版建议标签组限定在空间内 |
| tags | id, workspace_id, group_id, name | 空间内名称唯一；标签组必须同空间 |
| file_tags | file_id, tag_id | 复合唯一；双方必须同空间 |
| ignored_items | id, workspace_id, canonical_path, kind, active | 移除记录后保留；恢复时停用；首版以路径为忽略依据 |
| ai_profiles | id, provider, base_url, model, secret_ref, enabled | 仅保存密钥引用，不在业务数据库存明文 Key |
| ai_jobs | id, workspace_id, profile_id, task_id, purpose, status, created_at | purpose 为 document_analysis/query_assistance |
| ai_job_items | id, job_id, file_id, content_version, coverage, status, error_code | 固定所分析内容版本，记录各文件结果 |
| ai_suggestions | id, item_id, kind, payload, review_state, accepted_at | kind 为 category/tags/summary/name/group；payload 为经校验 JSON，不含任意执行命令 |
| proposed_names | file_id, name, source_suggestion_id, content_version, updated_at | file_id 唯一；已接受但未执行的名称 |
| consents | id, purpose, profile_id, payload_digest, scope_snapshot, confirmed_at | 固定本批实际发送的文件/片段/查询范围；不保存 Key |
| tasks | id, kind, state, total, completed, failed, cancel_requested, error_code | 进度与取消，不承诺进程重启后续跑 |
| operation_batches | id, workspace_id, revision, state, confirmed_at, consent_digest, created_at | 可编辑计划确认后冻结；修改计划需重新确认 |
| operation_items | id, batch_id, sequence, file_id, action, source_path, target_path, precondition, state, error_code, undo_state | 移动/改名逐项记录；执行和撤销独立状态 |
| operation_events | id, item_id, event_type, timestamp, details | 写入意图、完成、失败及恢复核对事件；不将文件系统当数据库事务 |

补充规则：

- Windows 路径规范化覆盖相对路径、大小写与分隔符；链接、联接点和硬链接需要独立识别。首版建议不递归跟随目录链接；同内容不同路径不视为重复文件。
- 分类方案变更影响所有引用它的空间；建议修改共享方案前提示影响空间，提供复制为新方案。此为待评审交互补充。
- 空间转移需事务更新归属及来源关系；目标不同方案时重选主分类或待分类。标签按名称映射到目标空间，组名冲突需展示映射，不能保留跨空间关联。原来源保留忽略记录，避免刷新抢回归属。此为待评审默认规则。
- 删除父类别含下级类别时，需展示受影响子类和文件，按用户选定目标统一转移或待分类；不删除磁盘文件。
- 标签合并先去重迁移关联，再删除旧标签；历史 AI 结果保留原始建议快照。
- 文件内容变化递增 content_version，旧 AI 结果标记过时；外部删除将记录标记 missing，不直接删除。移除管理时级联清理当前索引，历史操作保留不可变文件快照。
- 忽略按路径生效，外部改名后可能重新发现；首版不自动追踪外部移动。程序自己执行的移动保留 ID 并更新当前位置。
- 索引是可重建派生数据；保存正文后登记待索引状态，索引失败可在刷新时修复，不把未完成索引标为可检索。
- API Key 使用 Windows 系统凭据存储等方案，验证后选型；请求日志屏蔽 Key，错误信息避免泄露正文。

## 5. 状态设计

各维度分开保存，避免一个“已完成”掩盖不同状态。

| 对象 | 状态 |
| --- | --- |
| 解析 | pending / running / ready / partial / failed / unsupported |
| 文件可用性 | available / missing / inaccessible |
| 索引 | pending / ready / failed；对应内容版本 |
| AI 建议审核 | pending / accepted / rejected / stale |
| 后台任务 | queued / running / cancelling / completed / partial / failed / cancelled |
| 整理批次 | draft / confirmed / running / completed / partial / failed / cancelled / needs_recovery |
| 操作明细 | pending / executing / succeeded / skipped / failed / uncertain |
| 撤销明细 | not_requested / pending / succeeded / skipped / failed |

取消为协作取消：停止后续任务；已完成结果保留。正在执行的单次文件操作必须完成或进入恢复核对，不强制终止到不可判断状态。跨盘移动中取消不得丢失源文件。

## 6. 模块接口草案

统一返回 Result[T]（value 或 error(code, message, affected_ids)）；后台调用返回 TaskId。列表使用 Page[T]。下列是本地服务签名，不是 HTTP URL。

| 服务 | 接口 | 行为 |
| --- | --- | --- |
| WorkspaceService | create(name: str, scheme_id: Id) -> Workspace | 新建空间 |
| WorkspaceService | add_sources(space_id: Id, specs: list[SourceSpec]) -> ImportPreview | 规范化路径，报告排除/重复/跨空间冲突，不静默转移 |
| WorkspaceService | transfer(file_ids: list[Id], target_space: Id, mapping: TransferMapping) -> TransferResult | 更新归属、分类、标签、来源与忽略记录，不操作磁盘 |
| WorkspaceService | remove(file_ids: list[Id]) -> RemovalResult | 保留原文件；建立忽略，移除当前管理及索引 |
| WorkspaceService | restore_ignored(ignore_ids: list[Id]) -> TaskId | 恢复纳管并重新扫描 |
| DocumentService | refresh(space_id: Id, source_ids: list[Id]) -> TaskId | 更新来源与已移动受管文件；未变化内容不重新解析 |
| DocumentService | get_detail(file_id: Id) -> DocumentDetail | 正文、覆盖范围、路径、生成内容与状态 |
| CatalogService | save_category(input: CategoryInput) -> Category | 校验方案、父级、层级、重名 |
| CatalogService | delete_category(id: Id, reassignment: CategoryTarget) -> ChangeResult | 处理下级与归属，不操作文件 |
| CatalogService | assign(file_ids: list[Id], category_id: Id | None) -> ChangeResult | 同空间且同方案，支持待分类 |
| TagService | edit / bulk_attach / bulk_detach / merge | 校验空间、组归属与关联去重；对应输入为 TagInput/TagBatch/MergeTags |
| SearchService | search(space_id: Id, query: SearchQuery, page: PageRequest) -> Page[SearchHit] | SearchQuery 包含文本、类型、类别及标签；结果附真实片段与覆盖状态 |
| AIService | prepare_analysis(request: AnalysisRequest) -> TransmissionPreview | 固定 file_id/content_version、片段、模型与分类上下文；估算值标为估算 |
| AIService | run_analysis(preview_id: Id, consent_id: Id) -> TaskId | 确认范围一致才发送；内容或服务变化需重新预览 |
| AIService | prepare_query(space_id: Id, text: str) -> TransmissionPreview | 默认只发送查询及必要分类/标签上下文，不自动发送正文 |
| AIService | interpret_query(preview_id: Id, consent_id: Id) -> QueryProposal | 只生成受限结构化条件；不直接执行任意查询代码 |
| ReviewService | accept(suggestion_ids: list[Id], edits: ReviewEdits) -> ReviewResult | 校验内容版本、方案版本；分类/标签/名称分别生效，名称仅写 proposed_names |
| OperationService | build(request: PlanRequest) -> OperationPlan | 指定文件、动作、目标及名称，检查同批冲突与待分类文件 |
| OperationService | preflight(batch_id: Id) -> ValidationReport | 范围、文件状态、权限、冲突、路径及链接检查 |
| OperationService | confirm(batch_id: Id, revision: int) -> ConfirmedPlan | 固定计划内容与用户确认 |
| OperationService | execute(batch_id: Id) -> TaskId | 执行前复核，逐项日志，更新文件路径和来源关系 |
| OperationService | preview_undo(batch_id: Id) -> UndoPreview | 检查原路径占用、目标身份和外部变动 |
| OperationService | undo(preview_id: Id, confirmation: UndoConfirmation) -> TaskId | 预览后再次复核，按逆序条件性恢复 |
| TaskService | cancel(task_id: Id) -> TaskStatus | 取消后续工作，保留已完成结果 |
| SettingsService | save_profile / test_connection | 密钥入系统凭据存储；连接测试不发送文档 |

核心数据契约：SourceSpec={kind,path,recursive,exclusions}；SearchHit={file_id,current_path,matched_fields,snippet,coverage}；AnalysisRequest={space_id,file_ids,classification_mode,scheme_revision}；PlanRequest={space_id,file_ids,action,destination_mode,target_root,name_choices,conflict_choices}；OperationPlan={batch_id,revision,items,warnings,blocking_errors}。所有 file_id 必须先由业务层验证所属空间和当前管理状态。

## 7. 整理、改名与恢复细则

路径由本地程序根据主分类生成；待分类文件阻止移动并提示归类，不悄悄建立未确认目录。仅改名可在待分类时执行。类别名不得直接视为合法 Windows 路径：非法字符、保留名、长路径、大小写碰撞、父子源目标关系均需预检，路径调整必须出现在预览中。

原目录内整理：目录来源默认以所选来源目录为根，文件列表内明确显示各目标；单独添加且无目录来源的文件需用户指定根目录。重叠来源导致根目录不唯一时必须选择，不能由遍历顺序决定。此规则进入页面评审。

执行采用“不覆盖”语义，执行时即使出现竞态占用也不得覆盖。编号必须进入确认计划；确认后目标被占用则跳过或报失败，不静默改成另一个未确认名称。程序自己移动到新目录的文件仍由原空间管理，刷新检查当前路径，不要求重新扫描整个目标盘。

磁盘操作和数据库无法形成单一原子事务。先持久化操作意图，成功后落结果；崩溃后按源/目标身份核对，无法判断标为 uncertain 并要求处理。跨盘移动应先复制到受控临时目标、验证，再提交目标和移除源，任何阶段失败保留可核查数据，不宣称整批原子回滚。

撤销仅针对已成功项，先核对文件身份及原路径可用性，不覆盖新文件；部分撤销逐项报告。空目录仅在确认由该批创建且仍为空时才可清理。取消与撤销是两个动作，取消不会自动恢复已成功操作。

## 8. 按依赖排序的开发里程碑

每个里程碑先补充任务级实现计划；具体技术版本验证后锁定。此处列出交付、路径范围和有业务意义的验收，不代表已经执行测试。

| 顺序 | 任务及建议文件 | 依赖 | 可演示成果与验收 |
| --- | --- | --- | --- |
| M0 | 技术验证：spikes/desktop、parsing、search、cloud | 无 | 桌面最小窗口可打包启动；真实四类样本文字可提取，扫描 PDF 明示无正文；中文概念/短词/混合英文搜索对照；云端长文、失败与取消可验证，使用测试样本且不内置真实 Key |
| M1 | storage/migrations、workspaces/service.py、ui/library.py | M0 | 空间与来源可保存；同路径重复/跨空间冲突、重叠目录、排除与忽略恢复均可复现；重启保留配置 |
| M2 | documents/scanner.py、parsers/、tasks/service.py | M1 | 四类导入、正文展示和状态；失败隔离；内容变化才重解析；外部缺失提示；扫描取消保留完成结果 |
| M3 | catalog/categories.py、tags.py、ui/catalog.py | M2 | 两级和方案一致性；父类含下级浏览；类别删除重分配；批量标签及合并去重；转移空间不改磁盘 |
| M4 | search/index.py、service.py、ui/search.py | M2,M3 | 名称/正文/分类/标签可检索与筛选；真实片段；中文测试集；修改与移除后无旧命中，索引失败可刷新修复 |
| M5 | ai/provider.py、transmission.py、analysis.py、review.py、ui/review.py | M3,M4 | 用户 Key；逐批发送确认；长文覆盖记录；AI 结果校验与分项审核；名称建议不改磁盘；重新分析保留确认分类；内容过期拒绝直接接受；超时/错误不影响本地检索 |
| M6 | ai/query.py、ui/search.py | M4,M5 | AI 查询只解析条件，用户可修改；错误条件拒绝；无结果明确显示，无虚构文件；普通关键词搜索不调用云端 |
| M7 | operations/planner.py、validator.py、ui/plan.py | M3,M5 | 原目录/指定目录、主分类路径、独立改名、编号预览；未确认计划不能执行；待分类移动、非法路径及同批碰撞阻止 |
| M8 | operations/executor.py、recovery.py、undo.py、ui/history.py | M7 | 测试目录内移动/改名、冲突竞态、跨盘中断、部分成功、重启恢复核对和按批撤销；全部不覆盖外部文件 |
| M9 | ui/ 集成、打包配置、用户说明及演示样本 | M1-M8 | 全流程跑通；新 Windows 环境安装启动；无 Key 时基础管理可用；非 ASCII 路径、无权限、损坏文档、API 不可用均有可理解反馈 |

建议里程碑交付：M1-M4 为本地管理版本；M5-M6 为 AI 辅助版本；M7-M9 为完整课设版本。所有已确认功能均保留在最终首版范围中，分阶段不表示删减。

## 9. 验证重点与待评审项

重点验证：Windows 中文路径及长路径；中文检索召回；复杂 DOCX/PDF 文字覆盖；长文遗漏；云端超时及取消；重复添加和路径变化；磁盘/数据库状态不一致；撤销遇到外部修改。测试使用自建或明确允许的样本，文件操作使用隔离测试目录。

待评审的新增设计默认值：空间内标签作用域与跨空间映射；共享分类方案编辑提示；原目录整理根目录选择；AI 辅助查询的发送确认范围。它们不改变已经确认的功能清单，但需在相应界面原型中展示后收敛。

技术验证后再确定：GUI 与打包工具、数据库实现细节、中文索引方式、解析器、云端模型与分段参数、是否需要向量检索。尚未跑通参考仓库，不能假设其能力可直接复用。
