# RAG 项目整改 OpenCode 执行手册

> **给 OpenCode 的工作说明**
>
> 本文档是整改路线图和技术指导手册，不是代码实现说明。请按阶段小步提交，每个阶段独立可测、可回滚、可 review。
>
> **核心目标：** 把当前系统从“普通 PDF 文本聊天”推进到“保险条款专用 RAG”。第一优先级不是 Agent，也不是换模型，而是让每一个答案都能追溯到准确、完整、未污染的保险条款 chunk。

---

## 0. 总原则

### 0.1 工作方式

| 规则 | 要求 |
|---|---|
| 小步 PR | 每个阶段单独 PR，不要一次性重构所有链路 |
| 先测再改 | 每个 PR 先补最小可验证测试或基线记录，再实现 |
| 保留旧路径 | 新能力上线前保留旧逻辑兜底，避免全链路一次性断裂 |
| 数据可审计 | 解析、切块、检索、回答都要留下可检查的中间产物 |
| 指标先行 | 性能优化必须提供 before/after 数据 |
| 不堆新概念 | 暂时不要优先做 LangGraph 大重构、复杂 Agent、多模型评审 |

### 0.2 当前优先级判断

当前项目的主要问题分两类：

| 类型 | 影响 | 处理策略 |
|---|---|---|
| 入库质量问题 | 决定答案是否正确 | 最高优先级，优先改 PDF 解析、条款切块、metadata |
| 响应延迟问题 | 决定用户是否愿意使用 | 先做基线埋点和接口预留，证据链稳定后再深调响应体验 |
| 架构路线问题 | 决定后续返工成本 | PR-0 先锁定解析路由、质量门、向量库迁移策略和召回编排边界 |

先做 **PR-0 架构基线、解析路由与响应策略锁定**。PR-0 不负责重写完整业务链路，但必须把后续会影响大范围返工的路线先定住。

---

## 1. 总体执行顺序

| 阶段 | 优先级 | 主题 | 目标 |
|---|---|---|---|
| PR-0 | P0 必做 | 架构基线、解析路由与响应策略锁定 | 先锁定 Parser Router、Quality Gate、VectorStore 迁移边界和响应后置策略 |
| PR-1 | P0 必做 | PdfParserV2 | 用 PyMuPDF 替代 pypdf 主解析路径，产出可审计解析结果 |
| PR-2 | P0 必做 | InsuranceClauseChunker | 从字数切块改为条款号优先切块 |
| PR-3 | P0 必做 | Metadata 与 SQLite 升级 | 让 chunk 可筛选、可追溯、可用于证据校验 |
| PR-4 | P0 必做 | Golden QA 最小评测集 | 建立可重复验收闭环，不再靠感觉调参 |
| PR-5 | P1 | Query Intent 与同义词扩展 | 让检索理解保险问题类型 |
| PR-6 | P1 | Rule-based Retrieval Planner 与多路召回 | 按 intent 编排 dense、BM25/FTS、metadata filter、section targeted search |
| PR-7 | P2 | Milvus Lite Shadow Spike | 在 WSL2 试点 Milvus Lite，不直接替换 Chroma |
| PR-8 | P2 | BM25 稳定化与 RRF 去重 | 从内存索引走向可恢复、可解释检索 |
| PR-9 | P2 | 可信回答与证据校验 | 降低幻觉，保证数字、责任、免责结论有依据 |
| PR-10 | P3 | 前端证据链调试台与响应体验 | 提升 RAG 调试效率，最后再调流式、prompt 和答案体验 |

---

## 2. PR-0：架构基线、解析路由与响应策略锁定

### 2.1 为什么先做

本阶段是重要且紧急的路线锁定，不是完整功能重构。它要先回答三个会影响后续返工成本的问题：解析怎么路由、低质量解析怎么拦截、向量库迁移怎么试点。响应速度只做埋点和接口预留，等证据链稳定后再深调。

### 2.2 目标

| 目标 | 说明 |
|---|---|
| 解析路由锁定 | 明确 PDF、Markdown、TXT 以及未来 OCR 的路由边界 |
| 解析质量门锁定 | 低质量 PDF 不直接进入可信索引 |
| 响应优化后置 | 只保留耗时埋点、流式接口预留和缓存边界说明 |
| 向量库迁移边界 | 保留 Chroma 主路径，先抽象和评估，不直接切 Milvus Lite |
| 召回编排边界 | 先定义 RetrievalPlanner 输入输出方向，不在 PR-0 实现完整多路召回 |

### 2.3 涉及模块

| 文件或模块 | 关注点 |
|---|---|
| `rag-backend/app/services/rag_query_service.py` | 拆分 retrieve、rerank、generate 的耗时日志 |
| `rag-backend/app/dependencies.py` | 检查 embedding、vector store、reranker、generator 是否单例或缓存 |
| `rag-backend/app/main.py` | 如需要，将重资源放到应用启动阶段加载 |
| `rag-backend/app/infrastructure/parsers/` | 规划 ParserRouter 和 ParseQualityGate 的落点 |
| `rag-backend/app/infrastructure/vectorstores/chroma_store.py` | 检查 Chroma client 是否重复创建，查询参数是否合理 |
| `rag-backend/app/infrastructure/vectorstores/base.py` | 检查未来 Milvus Lite 是否能复用同一 VectorStore 抽象 |
| `rag-backend/app/infrastructure/generators/` | 检查是否支持流式输出或可扩展流式接口 |
| 前端 agent 调用入口 | 暂只确认 SSE 或 fetch stream 接入点，不在本 PR 深调体验 |

### 2.4 P0 决策

| 决策 | 要求 |
|---|---|
| 响应优化后置 | 不在 parser、chunk、metadata 未稳定前深调 prompt、首字延迟和答案话术 |
| PDF 解析必须走路由和质量门 | PyMuPDF 是主路径，但低质量解析必须被标记或阻断可信入库 |
| 向量库不立即替换 | Chroma 暂保留主路径，Milvus Lite 先做 PR-7 shadow spike |
| 多路召回先定接口 | RetrievalPlanner 先确定输入输出和 lanes 概念，完整实现放 PR-6 |

### 2.5 技术手段

| 问题 | 技术手段 |
|---|---|
| 不知道慢在哪 | 在每个 RAG 子步骤记录毫秒级耗时，包括 embed、vector query、BM25、RRF、rerank、context packing、LLM TTFB、LLM total |
| 每次请求重复初始化 | 使用应用级单例、依赖缓存或 FastAPI lifespan，把 embedding provider、Chroma client、reranker、generator 生命周期拉长 |
| PDF 解析路径不清 | 设计 ParserRouter：按文件类型、解析结果质量和未来 OCR 标记决定后续路径 |
| 低质量 PDF 污染索引 | 设计 ParseQualityGate：空文本、条款识别率低、页码污染、表格污染、疑似扫描件时阻断可信入库 |
| 向量库迁移风险高 | 检查 VectorStore 抽象，确认 Chroma 和未来 Milvus Lite 都能承载同一套 ids、texts、embeddings、metadata、delete、query 语义 |
| 本地检索 10 个 chunks 仍然 2 秒以上 | 检查是否请求时加载模型、是否磁盘路径错误、是否 Chroma collection 每次重建、是否查询前做了多余全量扫描 |
| LLM 阻塞返回 | 只预留流式生成接口和前端事件入口，不在本阶段深调 token 体验 |
| 缓存污染 | 缓存 key 必须包含 prompt、collection、collection index version、retrieval 参数、rerank 参数、prompt template version、LLM model |
| 云端 prompt caching 误用 | 只把它用于重复上下文的模型侧缓存，不把它当作向量检索缓存；检索缓存应在应用层实现 |

### 2.6 验收标准

| 验收项 | 标准 |
|---|---|
| 性能报告 | PR 说明中必须列出改前/改后耗时表 |
| Retrieve 拆分 | 能看到 embed、vector query、BM25、rerank 各自耗时 |
| 重资源初始化 | 日志能证明请求期间没有重复加载模型或重复初始化 Chroma client |
| ParserRouter 设计 | 文档或接口说明明确不同文件类型和 PDF 解析质量的路由 |
| Quality Gate 设计 | 明确哪些解析质量问题会阻断可信入库或标记人工/OCR |
| VectorStore 评估 | 明确 Chroma 继续主路径，Milvus Lite 只进入后续 shadow spike |
| 响应策略 | 明确流式、prompt、答案体验后置，不在本 PR 深调 |
| 不改业务语义 | 本 PR 不调整 chunk、metadata、prompt 语义逻辑，只锁定边界 |

### 2.7 Review 红线

| 红线 | 说明 |
|---|---|
| 只说“优化了性能”但没有数据 | 不通过 |
| 把 prompt caching 说成检索缓存 | 不通过 |
| 为了性能绕过引用、检索或安全校验 | 不通过 |
| 在请求处理函数里加载大模型 | 不通过 |
| 没有 ParserRouter 和 Quality Gate 的明确边界 | 不通过 |
| 把 Milvus Lite 写成 PR-0 直接替换 Chroma | 不通过 |

---

## 3. PR-1：PdfParserV2

### 3.1 目标

把主解析路径从 `pypdf.extract_text()` 升级为基于 PyMuPDF 的坐标级解析。PyMuPDF 是主路径，但不是唯一解析判断；pypdf 只能作为兜底或对照，不再作为主可信来源。目标不是“抽出一坨文本”，而是生成可审计、可清洗、可追溯的保险条款原始结构。

### 3.2 涉及模块

| 文件或模块 | 关注点 |
|---|---|
| `rag-backend/app/infrastructure/parsers/pdf_parser.py` | 新主解析逻辑 |
| `rag-backend/app/infrastructure/parsers/registry.py` | 接入 ParserRouter 选择结果 |
| `rag-backend/app/infrastructure/parsers/base.py` | 如需扩展 parser 返回结构，在此保持接口清晰 |
| `rag-backend/app/domain.py` | 如需新增 ParsedDocument、ParsedLine、ParseReport 等领域对象 |
| `rag-backend/app/services/ingestion_service.py` | 保存解析产物，不再只依赖 extracted text |
| `rag-backend/tests/test_parsers_and_chunker.py` | 增加解析质量测试 |

### 3.3 解析产物

每个上传文档建议保存以下产物：

| 产物 | 用途 |
|---|---|
| `original.pdf` | 原始文件留存 |
| `raw_lines.json` | 每行原文、页码、坐标、block、line 信息 |
| `parsed_clean.md` | 清洗后的可读正文，供切块使用 |
| `parse_report.json` | 解析质量、清洗动作、可疑行、表格候选记录 |

`parse_report.json` 至少要表达这些概念：

| 字段 | 用途 |
|---|---|
| `selected_parser` | 最终被选为主解析结果的解析器 |
| `parser_candidates` | 各候选解析器的质量摘要，例如 PyMuPDF、pypdf |
| `parse_quality_score` | 解析质量分，供入库质量门判断 |
| `needs_ocr` | 疑似扫描件或文本质量过低时标记，第一版不直接跑 OCR |
| `quality_warnings` | 页码污染、标题识别不足、表格风险、异常断词等问题 |

### 3.4 技术手段

| 能力 | 方法 |
|---|---|
| 文本与坐标抽取 | 使用 PyMuPDF 读取 page、block、line、span，保留页码和 bbox |
| 解析候选对照 | pypdf 只用于兜底和质量对照，不作为默认可信来源 |
| 页码清洗 | 识别单独数字、页脚数字、页眉页脚重复模式 |
| 页眉页脚清洗 | 统计跨页重复出现且位置接近的短文本，标记并移除 |
| 中文断词修复 | 修复异常空格、单字间隔、被 PDF 切开的中文词 |
| 跨页断句修复 | 当前页末尾不是句末标点且下一页开头延续时合并 |
| 条款标题保护 | 对类似 `2.4.1 重度疾病保险金` 的行保留为标题 |
| 表格候选识别 | 大量短行、对齐列、重复空格、医学分期关键词时标记为 table candidate |
| 质量评分 | 根据空行比例、可疑页码插入、表格候选、标题识别率生成质量分 |
| OCR 标记 | 疑似扫描件只设置 `needs_ocr`，第一版不落地完整 OCR 链路 |

### 3.5 最小验收样本

先选一份代表性保险 PDF 做样板，不要一开始批量处理所有 PDF。样板必须覆盖：

| 场景 | 验收点 |
|---|---|
| 条款标题 | `2.4.1`、`2.6`、`10.x`、`11.x`、`13.x` 等标题能保留 |
| 页码污染 | 类似夹在句子中间的页码应被移除或记录为可疑 |
| 中文断词 | 类似单字间隔、异常空格能被修复 |
| 跨页句子 | 不应把一个完整句子拆成两个不相关段落 |
| 表格 | TNM 分期等表格至少被识别为候选，不污染普通正文 |
| 质量门 | 低质量解析必须进入 warning 或 failed 状态，不直接生成可信 chunk |
| OCR 标记 | 扫描件或文本极少的 PDF 标记 `needs_ocr` |

### 3.6 Review 红线

| 红线 | 说明 |
|---|---|
| 仍以 `pypdf.extract_text()` 作为主路径 | 不通过 |
| 只输出纯文本，没有 raw lines 和 report | 不通过 |
| 丢失页码或坐标信息 | 不通过 |
| 表格被强行混进普通段落且无标记 | 不通过 |
| 疑似扫描件没有 `needs_ocr` 或质量 warning | 不通过 |
| 解析质量过低仍直接入库为可信 chunk | 不通过 |

---

## 4. PR-2：InsuranceClauseChunker

### 4.1 目标

把 chunk 从“字数块”升级为“保险判断单元”。用户问的是赔不赔、算不算、什么时候赔、免责不免责，所以 chunk 应对应条款、责任、疾病定义、释义或表格，而不是机械的 500 字。

### 4.2 涉及模块

| 文件或模块 | 关注点 |
|---|---|
| `rag-backend/app/infrastructure/chunkers/document_aware.py` | 新增或改造保险条款切块策略 |
| `rag-backend/app/infrastructure/chunkers/base.py` | 如需扩展 chunk metadata，保持接口稳定 |
| `rag-backend/app/domain.py` | 扩展 TextChunk 或新增更明确的 chunk 结构 |
| `rag-backend/tests/test_parsers_and_chunker.py` | 测试条款边界、疾病定义、免责条款 |
| `rag-backend/tests/test_dual_chunking.py` | 如现有测试涉及 parent-child，保持兼容或更新 |

### 4.3 切块优先级

| 优先级 | 边界 |
|---|---|
| 1 | 条款号边界 |
| 2 | 疾病定义边界 |
| 3 | 保险责任、责任免除、释义、理赔材料等业务边界 |
| 4 | 表格边界 |
| 5 | 自然段和句子边界 |
| 6 | 字数上限兜底 |

### 4.4 Chunk 类型建议

| chunk_type | 例子 |
|---|---|
| `clause` | 普通条款 |
| `insurance_liability` | 重度疾病保险金、轻度疾病保险金、身故保险金 |
| `exclusion` | 责任免除 |
| `mild_disease_definition` | 轻度疾病定义 |
| `critical_disease_definition` | 重度疾病定义 |
| `definition` | 释义 |
| `claim_material` | 理赔资料 |
| `table_candidate` | 暂无法完美还原但应独立保存的表格 |

### 4.5 技术手段

| 能力 | 方法 |
|---|---|
| 条款号识别 | 识别多级数字编号，例如 2、2.4、2.4.1、10.1、13.22 |
| 标题识别 | 结合行长度、编号、位置、前后空行判断标题 |
| 父子块 | child 用于检索，parent 用于回答上下文；二者通过 parent_id 关联 |
| 超长条款处理 | 保持条款内切分，不跨条款拆分；切分时保留 section_no 和 parent_id |
| 表格处理 | 表格候选单独成 chunk，先保证不污染普通条款 |
| 页码追踪 | chunk 的 page_start/page_end 来源于 raw_lines |

### 4.6 验收标准

| 验收项 | 标准 |
|---|---|
| 条款完整性 | `2.4.1 重度疾病保险金` 是一个完整语义 chunk 或一个 parent 下的完整子块组 |
| 免责独立 | `2.6 责任免除` 不和前后责任条款混在一起 |
| 疾病定义独立 | `10.x`、`11.x` 疾病定义不被拆坏 |
| 表格隔离 | `13.22 TNM 分期` 独立为 table candidate 或 table chunk |
| 字数兜底 | `chunk_size` 只在超长条款内部兜底，不作为主切块规则 |

### 4.7 Review 红线

| 红线 | 说明 |
|---|---|
| 仍然以固定字数为主切块策略 | 不通过 |
| chunk 没有 section_no 或 page 信息 | 不通过 |
| 疾病定义和责任条款混切 | 不通过 |
| 表格污染普通文本 chunk | 不通过 |

---

## 5. PR-3：Metadata 与 SQLite 升级

### 5.1 目标

让每个 chunk 可筛选、可解释、可追溯。SQLite 不应只存 preview，而应作为事实源、父块读取源和证据审计源。

### 5.2 涉及模块

| 文件或模块 | 关注点 |
|---|---|
| `rag-backend/app/infrastructure/repositories/sqlite.py` | 表结构、写入、读取、迁移兼容 |
| `rag-backend/app/infrastructure/repositories/base.py` | repository 接口扩展 |
| `rag-backend/app/infrastructure/vectorstores/chroma_store.py` | Chroma metadata 同步 |
| `rag-backend/app/services/ingestion_service.py` | 入库时写完整 metadata |
| `rag-backend/tests/test_sqlite_repository.py` | 表结构与读写测试 |
| `rag-backend/tests/test_chroma_vector_store.py` | metadata 透传测试 |

### 5.3 Metadata 字段建议

| 字段 | 用途 |
|---|---|
| `doc_id` | 文档标识 |
| `collection` | 知识库或业务集合 |
| `company` | 保险公司 |
| `product_name` | 产品名称 |
| `doc_type` | 文档类型，例如保险条款 |
| `section_no` | 条款号 |
| `section_title` | 条款标题 |
| `content_type` | 保险责任、免责、疾病定义等 |
| `chunk_type` | parent、child、table_candidate 等 |
| `parent_id` | 父块关联 |
| `page_start` | 起始页 |
| `page_end` | 结束页 |
| `source_file_sha256` | 源文件哈希 |
| `parser_version` | 解析器版本 |
| `chunker_version` | 切块器版本 |
| `embedding_model` | embedding 模型标识 |
| `quality_score` | 解析或 chunk 质量分 |

### 5.4 技术手段

| 能力 | 方法 |
|---|---|
| 完整 chunk 存储 | SQLite 存完整 `chunk_text`，preview 只用于展示 |
| 父块读取 | 通过 parent_id 读取 parent chunk，用于最终上下文 |
| Chroma metadata | 向量库中的 child chunk metadata 必须包含 section_no、content_type、parent_id、page_start/page_end |
| 版本管理 | 每次 parser、chunker、embedding 变更都应能识别老索引是否需要重建 |
| 重复文件处理 | 同 collection + 同 sha256 不重复解析；不同 collection 可复用解析产物但建立新的集合关系 |

### 5.5 验收标准

| 验收项 | 标准 |
|---|---|
| SQLite 存完整文本 | 能从 SQLite 拿到完整 chunk，而不只是 preview |
| Chroma metadata 完整 | 检索结果能带回 section_no、content_type、page_start/page_end、parent_id |
| 版本字段存在 | parser_version、chunker_version、source_sha256 可查询 |
| 父子关联正确 | 命中 child 后能稳定拿到 parent |
| 旧数据兼容 | 旧数据不存在新字段时，系统不崩溃，有合理兜底 |

### 5.6 Review 红线

| 红线 | 说明 |
|---|---|
| SQLite 仍只存 preview | 不通过 |
| metadata 只存在 Chroma，不存在 SQLite | 不通过 |
| page_start/page_end 丢失 | 不通过 |
| 修改表结构但没有迁移或兼容策略 | 不通过 |

---

## 6. PR-4：Golden QA 最小评测集

### 6.1 目标

建立可重复评测，不再靠“手动问几句感觉变好了”。第一版不需要大而全，先围绕一份样板保险 PDF 建 15 到 20 个问题。

### 6.2 涉及模块

| 文件或模块 | 关注点 |
|---|---|
| `rag-backend/tests/` | 增加评测测试或集成测试 |
| `rag-backend/data/evals/` 或类似目录 | 存放 Golden QA 数据 |
| `rag-backend/scripts/` | 如需要，增加评测运行脚本 |
| `rag-backend/app/services/rag_query_service.py` | 确保响应暴露引用和命中 chunk 信息 |

### 6.3 问题覆盖范围

| 类别 | 示例方向 |
|---|---|
| 等待期 | 等待期是多少，等待期内确诊怎么处理 |
| 重疾责任 | 60 岁前后重疾怎么赔 |
| 轻症责任 | 轻症赔几次，每次赔多少，赔完是否终止 |
| 身故/全残 | 身故、全残、重疾是否能重复赔 |
| 疾病定义 | 原位癌、单目失明、恶性肿瘤轻度/重度 |
| 责任免除 | 酒驾、艾滋病、故意行为等是否赔 |
| 理赔材料 | 申请理赔需要什么资料 |

### 6.4 每条评测数据应包含

| 字段 | 用途 |
|---|---|
| `question` | 用户问题 |
| `must_retrieve` | 必须命中的条款号或 content_type |
| `answer_contains` | 答案必须包含的关键事实 |
| `must_not_contain` | 答案不能出现的错误说法 |
| `must_cite_sections` | 必须引用的条款 |
| `notes` | 人工备注 |

### 6.5 指标

| 指标 | 说明 |
|---|---|
| Recall@5 | 正确条款是否进入前 5 个候选 |
| MRR | 正确条款排得是否足够靠前 |
| 答案关键点命中率 | 必要事实是否出现在答案里 |
| 禁止项命中率 | 错误事实是否被避免 |
| 引用准确率 | 答案引用是否指向正确条款 |

### 6.6 Review 红线

| 红线 | 说明 |
|---|---|
| 没有评测集就继续大改检索 | 不通过 |
| 只看答案文本，不看检索命中 | 不通过 |
| 测试问题没有 must_retrieve 或 must_not_contain | 不通过 |

---

## 7. PR-5：Query Intent 与同义词扩展

### 7.1 目标

查询端要理解保险问题类型。第一版不需要 LLM intent，规则加关键词即可，但输出结构要为后续 LLM intent 留接口。

### 7.2 涉及模块

| 文件或模块 | 关注点 |
|---|---|
| `rag-backend/app/services/rag_query_service.py` | intent 分析、query expansion |
| `rag-backend/app/domain.py` | 如需要，定义 intent 结果结构 |
| `rag-backend/tests/test_rag_query_service.py` | intent 分类与扩展测试 |

### 7.3 Intent 类型

| intent | 适用问题 |
|---|---|
| `benefit_query` | 赔多少、怎么赔、给付比例、保额 |
| `disease_definition` | 算不算疾病、属于轻症还是重疾 |
| `exclusion_query` | 免责、不赔、除外责任 |
| `waiting_period` | 等待期、观察期 |
| `age_rule` | 60 岁、18 岁、年龄限制 |
| `claim_materials` | 理赔资料、申请材料 |
| `comparison_query` | 多责任或多产品对比 |
| `summary_query` | 产品总结、保障概览 |

### 7.4 同义词扩展

| 用户词 | 扩展方向 |
|---|---|
| 重疾 | 重度疾病、重大疾病、大病 |
| 轻症 | 轻度疾病、轻疾 |
| 身故 | 死亡、身故保险金 |
| 豁免 | 免交保费、豁免保险费 |
| 等待期 | 观察期、90 天等具体值 |
| 免责 | 责任免除、不承担保险责任 |
| 赔 | 给付、保险金、赔付 |

### 7.5 技术手段

| 能力 | 方法 |
|---|---|
| 规则 intent | 用关键词和短语匹配先覆盖高频保险问题 |
| 扩展 query | 保留原 query，同时生成扩展 query，不替换用户原话 |
| 检索提示 | intent 输出应能告诉 retriever 优先查哪些 content_type 和 section 范围 |
| Debug 输出 | 响应中可选暴露 intent 和 expanded queries，方便调试 |

### 7.6 Review 红线

| 红线 | 说明 |
|---|---|
| intent 仍然只是原 query 透传 | 不通过 |
| 扩展 query 覆盖掉用户原 query | 不通过 |
| intent 分类没有测试 | 不通过 |

---

## 8. PR-6：Rule-based Retrieval Planner 与多路召回

### 8.1 目标

不同保险问题需要不同证据组合。不能机械拿向量 top_k，也不能盲目扩父块。本阶段用规则型 RetrievalPlanner 编排多路召回，暂不使用 LLM Planner，确保每条召回路径都可测试、可解释、可复现。

### 8.2 Planner 输入输出

| 项 | 要求 |
|---|---|
| 输入 | 原始问题、intent、expanded_queries、collection、可用 metadata 字段 |
| 输出 | 多条 retrieval lanes，每条 lane 明确检索方式、过滤条件、top_k、权重、目标 content_type |
| 调试信息 | 响应中可追踪每条 lane 的命中、排序、融合前后变化 |
| 第一版限制 | 只做规则 Planner，不接 LLM Planner |

### 8.3 多路召回通道

| lane | 用途 |
|---|---|
| dense vector | 语义相似召回，覆盖用户表达和条款表达不一致的情况 |
| BM25/FTS | 关键词、条款号、疾病名、数字、百分比精确召回 |
| metadata filter | 按 content_type、section_no、doc_type、page、product 过滤或 boost |
| section targeted search | 面向 `2.4.*`、`2.6`、`10.*`、`11.*`、`13.*` 等条款范围定向召回 |

### 8.4 Intent 对应召回策略

| intent | 检索侧重点 |
|---|---|
| `benefit_query` | 优先保险责任、给付比例、年龄敏感条款 |
| `disease_definition` | 优先疾病定义、释义、相关医学表格 |
| `exclusion_query` | 同时召回责任免除和相关疾病定义 |
| `waiting_period` | 优先等待期、责任生效、退还保费等条款 |
| `claim_materials` | 优先理赔申请、资料提交、流程条款 |

### 8.5 证据覆盖规则

| 问题类型 | 必须尝试覆盖 |
|---|---|
| 赔不赔 | 保险责任、责任免除、相关疾病定义 |
| 疾病算不算 | 疾病定义、释义、表格候选 |
| 赔多少 | 保险责任、给付比例、年龄/次数/等待期条件 |
| 等待期 | 等待期定义、等待期内处理、等待期后责任 |
| 多产品对比 | 每个产品各自召回同类型条款，禁止只用一个产品的证据推另一个产品 |

### 8.6 父块扩展策略

| 问题类型 | 扩展方式 |
|---|---|
| 疾病定义 | 扩展当前疾病定义完整条款 |
| 保险责任 | 扩展当前责任条款及相关特别注意事项 |
| 免责问题 | 扩展责任免除整条及相关定义 |
| 理赔材料 | 扩展理赔申请和材料条款 |

### 8.7 去重策略

| 维度 | 规则 |
|---|---|
| chunk_id | 完全去重 |
| parent_id | 同一 parent 最多保留少量 child |
| doc_id + section_no | 同一条款避免刷屏 |
| content_type | 最终上下文尽量覆盖多个必要证据类型 |

### 8.8 验收标准

| 验收项 | 标准 |
|---|---|
| Planner 可解释 | 每次查询能看到触发了哪些 lanes |
| 多路召回生效 | dense、BM25/FTS、metadata filter、section targeted search 至少有可测试路径 |
| 赔不赔覆盖 | 赔不赔类问题必须尝试召回责任、免责、疾病定义 |
| 疾病定义覆盖 | 疾病算不算类问题必须优先查疾病定义、释义、表格候选 |
| 融合去重 | 多路命中同一条款时最终上下文不刷屏 |

### 8.9 Review 红线

| 红线 | 说明 |
|---|---|
| 所有 intent 使用同一套扩展逻辑 | 不通过 |
| 同一条款在最终上下文反复刷屏 | 不通过 |
| 问赔不赔时完全不查免责 | 不通过 |
| 疾病算不算时不查疾病定义或释义 | 不通过 |
| 使用 LLM Planner 替代第一版规则 Planner | 不通过 |

---

## 9. PR-7：Milvus Lite Shadow Spike

### 9.1 目标

评估 Milvus Lite 是否适合替代 Chroma 的本地向量存储，但不在本阶段直接切主路径。先通过 shadow write/search 对比同一批 chunk 在 Chroma 和 Milvus Lite 中的召回质量、metadata filter 能力、删除重建能力和耗时。

### 9.2 环境策略

| 项 | 要求 |
|---|---|
| 运行环境 | 优先 WSL2 Ubuntu，不走 Windows 原生 Python 3.13 |
| Python 版本 | 建议固定 Python 3.11 或 3.12，降低 ML/向量库依赖兼容风险 |
| 内存判断 | 当前约 16GB 内存，可以做本地小规模试点，但不能据此直接判定适合长期生产 |
| 主路径 | Chroma 继续保留为主 vector provider |

### 9.3 技术手段

| 能力 | 方法 |
|---|---|
| 适配器试点 | 新增 Milvus Lite VectorStore 适配器，复用现有 VectorStore 抽象 |
| Shadow write | 同一批 chunks 同时写入 Chroma 和 Milvus Lite |
| Shadow search | 同一 query 同时查询 Chroma 和 Milvus Lite，对比 top_k 和耗时 |
| Metadata filter | 验证 section_no、content_type、doc_id、collection、parent_id 等过滤条件 |
| 删除重建 | 验证按 document_id 删除、按 collection 重建、重复入库覆盖 |
| 迁移判断 | 只有 shadow 对比通过后，后续 PR 才能讨论主路径切换 |

### 9.4 验收标准

| 验收项 | 标准 |
|---|---|
| 安装验证 | WSL2 环境能稳定安装并运行 Milvus Lite |
| 写入验证 | 同一批 chunks 可完整写入 Chroma 和 Milvus Lite |
| 检索对比 | Golden QA 样本能输出 Chroma vs Milvus Lite top_k 对比 |
| 过滤验证 | Milvus Lite metadata filter 能覆盖当前 schema 的核心字段 |
| 删除验证 | document 级删除和 collection 级重建行为清晰可测 |
| 不切主路径 | 本 PR 完成后 Chroma 仍是默认主路径 |

### 9.5 Review 红线

| 红线 | 说明 |
|---|---|
| 直接把 Chroma 主路径替换成 Milvus Lite | 不通过 |
| 只验证写入，不验证 metadata filter | 不通过 |
| 不用 Golden QA 或固定样本做召回对比 | 不通过 |
| 忽略 Windows Python 3.13 兼容风险 | 不通过 |
| 没有删除、重建、重复入库验证 | 不通过 |

---

## 10. PR-8：BM25 稳定化与 RRF 去重

### 10.1 目标

内存 BM25 可以继续作为早期实现，但正式能力应能重启恢复、可重建、可按 collection 管理。

### 10.2 技术路线

| 阶段 | 技术手段 |
|---|---|
| 短期 | 保持 MemoryBM25，但启动时从 SQLite 重建，并补齐 collection 隔离 |
| 中期 | 迁移到 SQLite FTS5，减少重启丢失和多进程不一致 |
| 长期 | 数据量上来后再考虑 Tantivy、OpenSearch、Elasticsearch |

### 10.3 RRF 要求

| 要求 | 说明 |
|---|---|
| 向量和 BM25 同一 chunk 合并 | 不允许同一 chunk 双重出现 |
| RRF 前后有 debug 信息 | 能看到 vector rank、BM25 rank、RRF score |
| RRF 后再去重 | 按 chunk_id、parent_id、section_no 控制多样性 |

### 10.4 Review 红线

| 红线 | 说明 |
|---|---|
| Worker 重启后 BM25 直接丢失且无重建 | 不通过 |
| BM25 不按 collection 隔离 | 不通过 |
| RRF 后没有去重 | 不通过 |

---

## 11. PR-9：可信回答与证据校验

### 11.1 目标

保险 RAG 不能只“看起来有引用”，必须让关键结论被证据托住。尤其是赔付比例、年龄、等待期、次数、免责结论。

### 11.2 技术手段

| 能力 | 方法 |
|---|---|
| 保险专用 prompt | 强制只基于资料回答，不得根据常识补充保险责任 |
| 数字校验 | 答案中的数字、百分比、年龄、次数必须出现在证据中 |
| 责任校验 | 赔、不赔、终止、豁免等结论必须有对应引用 |
| 范围校验 | 防止轻症、重疾、身故、全残规则混用 |
| 无证据降级 | 资料不足时明确说无法确认，不强答 |

### 11.3 推荐答案结构

| 部分 | 用途 |
|---|---|
| 结论 | 简明回答 |
| 依据 | 引用条款和页码 |
| 注意事项 | 免责、年龄、等待期、次数限制 |
| 未确认信息 | 当前资料无法确认的部分 |

### 11.4 Review 红线

| 红线 | 说明 |
|---|---|
| 只检查引用编号存在 | 不通过 |
| 答案出现证据中不存在的数字 | 不通过 |
| 问免责时只引用责任条款 | 不通过 |
| 资料不足仍然强答 | 不通过 |

---

## 12. PR-10：前端证据链调试台与响应体验

### 12.1 目标

调试时能回答这些问题：为什么召回它？为什么没召回正确条款？BM25 命中了什么？向量命中了什么？reranker 为什么排序？最后 LLM 用了哪些证据？证据链稳定后，再调流式输出、prompt 细节和答案体验。

### 12.2 响应中建议增加的 debug 信息

| 字段 | 用途 |
|---|---|
| `intent` | 问题类型 |
| `expanded_queries` | 同义词扩展后的 query |
| `vector_hits` | 向量召回列表 |
| `bm25_hits` | 关键词召回列表 |
| `rrf_hits` | 融合排序 |
| `rerank_hits` | 重排结果 |
| `final_context` | 最终给 LLM 的证据 |
| `used_in_answer` | 证据是否被答案引用 |

### 12.3 响应体验后置要求

| 项 | 要求 |
|---|---|
| 流式输出 | 等证据链稳定后再优化首字延迟和 token 级体验 |
| Prompt 调整 | 以 Golden QA 和证据校验结果为依据，不凭主观感觉改 |
| Prompt caching | 只作为模型侧重复上下文优化，不当作检索缓存 |
| 答案话术 | 不牺牲证据准确性换流畅度 |

### 12.4 Review 红线

| 红线 | 说明 |
|---|---|
| 只显示最终答案，不显示证据链 | 不通过 |
| debug 信息缺少 section_no/page | 不通过 |
| 前端展示让普通用户误以为 debug 是答案正文 | 不通过 |
| 在证据链稳定前大改 prompt 或答案话术 | 不通过 |
| 把 prompt caching 当作检索缓存 | 不通过 |

---

## 13. 暂时不要做的事

| 暂停项 | 原因 |
|---|---|
| 复杂 Agent 或 LangGraph 大重构 | 当前瓶颈不是工作流编排，而是入库对象质量和检索证据质量 |
| 大规模批量导入全部 PDF | 单份样板 PDF 没跑通前，批量只会制造污染 |
| 盲目更换 embedding 模型 | 没有 Golden QA 前无法判断收益 |
| 表格完美还原 | 第一阶段先识别并隔离 table candidate |
| 多模型自动评审 | 先把基础证据链做对 |
| 围绕 pypdf 继续调参 | 主路径应迁移到 PyMuPDF 坐标解析 |
| 立刻把 Chroma 主路径替换成 Milvus Lite | 先做 WSL2 shadow spike，对比通过后再决定是否切换 |
| 现在深调响应话术、prompt caching、首字延迟体验 | 等 parser、chunk、metadata、证据链稳定后再调 |
| 第一版直接接 OCR 全链路 | 先做 `needs_ocr` 标记，避免依赖、性能和调试复杂度同时上升 |

---

## 14. 每个 PR 的交付格式

OpenCode 每个 PR 完成后，应在说明中包含：

| 内容 | 要求 |
|---|---|
| 改动摘要 | 用 3 到 8 条说明做了什么 |
| 涉及文件 | 列出主要修改文件 |
| 行为变化 | 说明用户可见或数据结构变化 |
| 测试结果 | 列出运行过的测试命令和结果 |
| 性能数据 | 涉及性能时必须有 before/after |
| 数据迁移 | 涉及 SQLite 或索引时必须说明兼容策略 |
| 未解决问题 | 不确定事项要列出来，不要悄悄猜 |

---

## 15. 总体验收 Checklist

| 项 | 验收问题 |
|---|---|
| Architecture | PR-0 是否锁定 ParserRouter、Quality Gate、VectorStore 迁移边界和响应后置策略 |
| Parser Router | 不同文件类型和低质量 PDF 是否有清晰路由 |
| Quality Gate | 解析质量不足时是否会 warning、failed 或 `needs_ocr`，而不是直接可信入库 |
| Parser | PDF 是否能生成 raw_lines、parsed_clean、parse_report |
| Parser | 页码、页眉、页脚污染是否明显减少 |
| Parser | 条款标题、页码、坐标是否可追溯 |
| Chunker | 是否按条款号和保险语义切块 |
| Chunker | 疾病定义、责任免除、表格是否被正确隔离 |
| Metadata | chunk 是否包含 section_no、content_type、page_start/page_end |
| SQLite | 是否保存完整 chunk_text 和 parent 关系 |
| Retrieval Planner | 是否能按 intent 输出多条可解释 retrieval lanes |
| Retrieval | 赔不赔类问题是否同时尝试召回责任、免责、疾病定义 |
| Retrieval | 是否能按 intent 优先召回正确类型条款 |
| Retrieval | RRF 后是否有去重和多样性控制 |
| Milvus Shadow | Milvus Lite 是否只做 shadow 对比，且 Chroma 仍是默认主路径 |
| Milvus Shadow | 是否验证写入、检索、metadata filter、删除和重建 |
| Answer | 关键数字和责任结论是否有证据支撑 |
| Eval | Golden QA 是否能重复运行 |
| Performance | 是否有清晰耗时拆分和首字延迟指标 |
| UX | 前端是否能查看证据链调试信息 |
| Response | 流式、prompt、答案话术是否等证据链稳定后再调 |

---

## 16. 最关键的判断标准

后续所有技术决策，都用这句话判断：

**用户问一个保险问题时，系统必须先找到准确、完整、未污染的条款 chunk，再让 LLM 基于该 chunk 回答，并且答案能追溯回原 PDF 页码和条款号。**

做不到这一点，就先不要继续扩 Agent、换模型或批量导入更多 PDF。
