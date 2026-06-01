# RAG 后端优化 · 工作指南

> 本指南描述一项 RAG 后端重构任务，包含 **内存 BM25 + 向量双路召回（RRF 融合 + CrossEncoder 重排）** 以及 **小块检索 / 大块读取（Parent-Child）**。
>
> **验收人（代码大师）**：上一个会话的 AI
> **工作模式**：你只负责写代码和跑测试，遇到不确定的设计决策，**记录下来** 而不是自己猜。
> **交付标准**：下文所有「验收标准」必须全部满足，才算完成。

---

## 目录

1. [任务概述](#1-任务概述)
2. [文件清单 & 职责](#2-文件清单--职责)
3. [详细实现要求](#3-详细实现要求)
4. [验收标准](#4-验收标准)
5. [代码质量与安全红线](#5-代码质量与安全红线)
6. [测试要求](#6-测试要求)
7. [常见陷阱 & 决策备忘](#7-常见陷阱--决策备忘)

---

## 1. 任务概述

### 1.1 现状

| 环节 | 当前实现 |
|------|----------|
| 检索 | 单路 ChromaDB 向量检索 |
| 分块 | `DocumentAwareChunker(chunk_size=500, overlap=50)`，单一套 chunk |
| 重排 | HTTP API 调 `localhost:9000/v1/rerank`（cross-encoder 模型） |
| Embedding | HTTP API 调 `localhost:9000/v1/embeddings`（text2vec 模型） |
| 模型加载 | 依赖外部 API 进程，FastAPI 启动时不加载任何模型 |
| 并发安全 | 无相关考虑 |

### 1.2 目标架构

```
FastAPI 启动时 (lifespan):
  ├─ SentenceTransformer("shibing624/text2vec-base-chinese")  → 全局 embedder
  ├─ CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1") → 全局 reranker
  └─ 从 SQLite 读全量子块 → MemoryBM25Indexer.rebuild()

Ingestion:
  parse → DocumentAwareChunker 双路切分
    ├─ Parent (chunk_size=1500-2000)  → SQLite (chunks 表, type='parent')
    └─ Child  (chunk_size=300)        → Embed → ChromaDB + SQLite + BM25Indexer.add()

Query:
  query → [ChromaDB 查 Top-10 子块] + [BM25Indexer.search 查 Top-10 子块]
        → RRF 融合 → CrossEncoder 重排 → Top-3 子块
        → 提取 parent_id → SQLite 捞取完整父块（去重）→ LLM
```

---

## 2. 文件清单 & 职责

### 2.1 新增文件

| # | 文件 | 职责 |
|---|------|------|
| 1 | `app/retrieval/bm25_indexer.py` | `MemoryBM25Indexer` 类 + `rrf_fusion()` 函数 |
| 2 | `app/retrieval/__init__.py` | 空文件，使 retrieval 成为 Python 包 |

### 2.2 修改文件

| # | 文件 | 改动量 |
|---|------|--------|
| 3 | `app/main.py` | lifespan 增加模型加载 + BM25 初始化逻辑 |
| 4 | `app/services/ingestion_service.py` | 双路分块、parent 存 SQLite、child 进 BM25 |
| 5 | `app/services/rag_query_service.py` | 双路召回 + RRF + CrossEncoder + parent 捞取 |
| 6 | `app/infrastructure/chunkers/document_aware.py` | 增加 `dual_split()` 方法，一次返回 (parents, children) |
| 7 | `app/dependencies.py` | embedder 切回本地模式、暴露全局模型 |
| 8 | `.env` | `EMBEDDING_PROVIDER` 从 `api` 改为默认 |

### 2.3 可能需要的变更

| # | 文件 | 说明 |
|---|------|------|
| 9 | `app/domain.py` | 可能需要新增 `ChunkRecord` 或扩展 `TextChunk` |
| 10 | `app/infrastructure/repositories/sqlite.py` | `chunks` 表可能需要加 `parent_id` 列、`type` 列 |
| 11 | `app/infrastructure/repositories/base.py` | 可能需要加 `store_parent_chunk()` / `get_parent_chunk()` |

---

## 3. 详细实现要求

### 3.1 `app/retrieval/bm25_indexer.py`

#### 3.1.1 `MemoryBM25Indexer`

**构造**

```python
class MemoryBM25Indexer:
    def __init__(self):
        self._doc_pool: list[str] = []
        self._bm25: BM25Okapi | None = None
        self._lock = threading.Lock()
        self._stopwords: set[str] = {
            "的", "了", "在", "是", "我", "我们", "你", "您",
            "本合同", "按照", "依据", "本条款", "上述", "以下",
            "之", "与", "和", "或", "及", "等", "有", "不",
            "被", "将", "把", "从", "对", "为", "以", "由",
            "于", "向", "到", "让", "该", "这个", "那个", "其",
            "它", "他们", "它们", "没有", "可以", "会", "能",
            "要", "已经", "还", "都", "只", "但", "而", "且",
            "如果", "若", "则", "如", "因", "所以", "因此",
        }
        self._k1: float = 1.8
        self._b: float = 0.4
```

**方法**

| 方法 | 签名 | 说明 |
|------|------|------|
| `_tokenize` | `(text: str) -> list[str]` | jieba.cut → 去停用词 → 去空白 |
| `rebuild` | `(chunks: list[str]) -> None` | **全量**重建。设置新 doc_pool → tokenize → BM25Okapi |
| `add` | `(text: str) -> None` | doc_pool.append → 立即全量 rebuild。**必须持有锁** |
| `remove` | `(text: str) -> None` | 从 doc_pool 移除 → 立即全量 rebuild。暂可不实现 |
| `search` | `(query: str, top_n: int = 10) -> list[str]` | 返回 **文本列表**（不是索引） |

**并发安全**

```python
def add(self, text: str) -> None:
    with self._lock:
        self._doc_pool.append(text)
        tokenized = [self._tokenize(d) for d in self._doc_pool]
        self._bm25 = BM25Okapi(tokenized, k1=self._k1, b=self._b)

def search(self, query: str, top_n: int = 10) -> list[str]:
    with self._lock:
        if not self._bm25 or not self._doc_pool:
            return []
        return self._bm25.get_top_n(self._tokenize(query), self._doc_pool, n=top_n)
```

> **为什么 add 里全量 rebuild 可以接受？** 项目当前数据量很小（~百级 chunk），全量 BM25 构建 < 1ms。未来数据增长后，可考虑定期批量 rebuild + 独立增量结构，但当前不需要。

#### 3.1.2 `rrf_fusion()`

```python
def rrf_fusion(
    vector_results: list[dict],  # 每个 dict 必须有 "id" 和 "contentPreview"
    bm25_results: list[str],     # 文本列表
    k: int = 60,
) -> list[dict]:
```

- 通过 **contentPreview 文本完全匹配** 来确定两个 list 中的同一文档
- 每个文档的 RRF score = Σ 1/(k + rank_i)
- 按 score 降序返回
- 返回格式与 `vector_results` 一致（dict 列表）

---

### 3.2 `app/main.py` — Lifespan 模型加载

**必须使用 FastAPI `@asynccontextmanager lifespan` 模式。**

```python
from contextlib import asynccontextmanager
from sentence_transformers import SentenceTransformer, CrossEncoder
from app.infrastructure.repositories.sqlite import SQLiteRepository
from app.retrieval.bm25_indexer import MemoryBM25Indexer

app_state: dict = {
    "embedding_model": None,    # SentenceTransformer
    "cross_encoder": None,      # CrossEncoder
    "bm25_indexer": None,       # MemoryBM25Indexer
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 加载本地模型（从缓存，秒级）
    print("[lifespan] Loading embedding model...")
    app_state["embedding_model"] = SentenceTransformer("shibing624/text2vec-base-chinese")
    print("[lifespan] Loading cross-encoder model...")
    app_state["cross_encoder"] = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")

    # 2. 从 SQLite 加载全量子块 → BM25
    repo = SQLiteRepository("sqlite:///./data/rag.sqlite")
    repo.initialize()
    # repo 需要有一个新方法 list_all_child_texts() → list[str]
    all_chunks = repo.list_all_child_texts()
    print(f"[lifespan] Loading {len(all_chunks)} child chunks into BM25...")
    bm25 = MemoryBM25Indexer()
    bm25.rebuild(all_chunks)
    app_state["bm25_indexer"] = bm25

    yield
    # 关闭时清理（如有必要）

app = FastAPI(lifespan=lifespan)
```

> **注意**：`SQLiteRepository` 可能需要加一个 `list_all_child_texts()` 方法，查询 `chunks` 表中所有 `type='child'` 的 `content_preview` 或新增的 `text` 字段。

---

### 3.3 `app/services/ingestion_service.py` — 双路分块

#### 3.3.1 分块策略

现有 `DocumentAwareChunker` 保持不变。新增 `dual_split()` 方法：

```python
def dual_split(self, text: str) -> tuple[list[TextChunk], list[TextChunk]]:
    """
    返回 (parents, children)
    parents:  chunk_size=1500-2000
    children: chunk_size=300
    """
```

或者更简单：分别用两种 chunk_size 调两次 `split()`。验收人不指定具体实现，两条路都可以，**验收标准是结果正确**。

#### 3.3.2 Ingestion 流程

```python
def ingest_document(self, job_id, document_id, collection):
    # ... 前处理（parse, normalize）不变 ...

    # === dual split ===
    parents, children = self.chunker.dual_split(parsed_text)

    # === parent chunks → SQLite（只存文本，不向量化） ===
    parent_metadatas = []
    for p_idx, parent in enumerate(parents):
        parent_id = f"{document_id}:parent:{p_idx}"
        # 存 SQLite
        self.repository.store_parent_chunk(
            id=parent_id,
            document_id=document_id,
            collection=collection,
            text=parent.text,
            chunk_index=p_idx,
        )
        parent_metadatas.append({"parent_id": parent_id})

    # === 分配 parent 给每个 child ===
    # 简单做法：按文本 overlap 分配
    # 更简单的做法：顺序分配（每 N 个 child 对应一个 parent）
    # 验收人推荐做法：
    #   遍历 child，对每个 child 找文本 overlap 最大的 parent
    #   或最简单的：用 chunk_index 范围映射
    def _assign_parent(child_index, total_children, total_parents):
        p = int(child_index * total_parents / total_children)
        return min(p, total_parents - 1)

    # === child chunks → Embed → ChromaDB + SQLite + BM25 ===
    child_ids = []
    child_texts = []
    child_metadatas = []
    for c_idx, child in enumerate(children):
        child_id = f"{document_id}:{c_idx}"
        p_idx = _assign_parent(c_idx, len(children), len(parents))
        child_ids.append(child_id)
        child_texts.append(child.text)
        child_metadatas.append({
            "document_id": document.id,
            "filename": document.filename,
            "collection": collection,
            "chunk_index": c_idx,
            "parent_id": f"{document_id}:parent:{p_idx}",
            "type": "child",
            # ... 保留原有 metadata ...
        })

    # Embed + ChromaDB upsert（同现有逻辑）
    embeddings = self.embedding_provider.embed_texts(child_texts)
    self.vector_store.delete_chunks(collection=collection, where={"document_id": document_id})
    self.vector_store.upsert_chunks(
        collection=collection, ids=child_ids, texts=child_texts,
        embeddings=embeddings, metadatas=child_metadatas,
    )

    # SQLite 记录 child chunks（需扩展现有 replace_chunks 或新增方法）
    self.repository.replace_chunks(
        document_id=document_id,
        collection=collection,
        chunks=[{
            "chunk_index": c.chunk_index,
            "chroma_id": child_ids[i],
            "content_preview": c.text[:200],
            "token_count": c.token_count,
            "source_file": document.filename,
            "upload_time": document.created_at,
            "parent_id": child_metadatas[i]["parent_id"],
            "type": "child",
        } for i, c in enumerate(children)],
    )

    # === BM25 增量 ===
    bm25_indexer = get_bm25_indexer()  # 从依赖注入或全局获取
    for child_text in child_texts:
        bm25_indexer.add(child_text)

    # ... 后续标记成功等不变 ...
```

> **验收人要强调的**：
> - SQLite `chunks` 表需要加 `parent_id TEXT` 和 `type TEXT DEFAULT 'child'` 列（或者新建 `parent_chunks` 表）
> - ChromaDB metadata 里必须带 `parent_id`
> - Parent chunk 的文本**存 SQLite 完整字段**（当前 `chunks` 表只有 `content_preview`，需要用完整字段或扩展现有字段）

---

### 3.4 `app/services/rag_query_service.py` — 双路召回 + RRF + CrossEncoder + Parent 捞取

**核心改动在 `run()` 方法的 retrieve_context ~ rerank_context 阶段。**

```python
from app.retrieval.bm25_indexer import rrf_fusion

class RagQueryService:
    def __init__(self, ..., app_state: dict):
        # ... 现有参数 ...
        self._app_state = app_state
        self._cross_encoder = app_state["cross_encoder"]
        self._bm25_indexer = app_state["bm25_indexer"]

    def run(self, prompt, collection, agent_id, thread_id):
        # ... 前面不变，直到 retrieve_context ...

        # === 1. 向量检索子块 Top-10 ===
        query_embedding = self._embedder.embed_texts([intent["query"]])[0]
        raw_matches = self._vector_store.query_chunks(
            collection, query_embedding, n_results=10
        )
        vector_matches = [_serialize_vector_match(m, i, collection)
                          for i, m in enumerate(raw_matches)]

        # === 2. BM25 检索子块 Top-10 ===
        bm25_texts = self._bm25_indexer.search(intent["query"], top_n=10)

        # === 3. RRF 融合 ===
        fused = rrf_fusion(vector_matches, bm25_texts, k=60)

        if not fused:
            # 返回无结果响应
            ...

        # === 4. CrossEncoder 重排 Top-3 ===
        pairs = [(intent["query"], item["contentPreview"]) for item in fused]
        scores = self._cross_encoder.predict(pairs)
        scored = list(zip(fused, scores))
        scored.sort(key=lambda x: x[1], reverse=True)
        top3 = scored[:3]

        # === 5. 提取 parent_id → 捞取完整父块（去重） ===
        seen_parents = set()
        final_contexts = []
        for item, score in top3:
            parent_id = item.get("metadata", {}).get("parent_id")
            if not parent_id or parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            parent_text = self._repository.get_parent_chunk(parent_id)
            if parent_text:
                final_contexts.append({
                    **item,
                    "contentPreview": parent_text,  # 替换为完整父块
                    "parent_id": parent_id,
                    "child_ids": [item["id"]],
                })

        # === 6. 后续 ===
        # 用 final_contexts（而不是 vector_matches）进行 pack_context、generate 等
        # rerank_context step 记录最终结果
        # expand_parent_context 可以跳过（已在此处处理）
```

> **验收注意**：
> - 当前 `_expand_parent_context` 做的是邻居 chunk 合并，现在被 parent 捞取替代。建议**保留旧的邻居合并作为兜底**：如果 parent_id 不存在或捞取失败，回退到原有的 `_expand_parent_context`。
> - `_serialize_vector_match` 需要确保 `metadata.parent_id` 透传到最终响应。

---

## 4. 验收标准

### 4.1 功能验收

| # | 验收项 | 检测方法 |
|---|--------|----------|
| F1 | FastAPI 启动时加载模型（无外部 API） | 启动日志打印 `[lifespan]` 信息，无网络请求到 9000 端口 |
| F2 | BM25 索引在 lifespan 阶段完成初始化 | 从 SQLite 读取已有 chunks，BM25.search() 返回非空结果 |
| F3 | 上传文档后，子块同时进入 ChromaDB + SQLite + BM25 | 分别检查三个存储均有新数据 |
| F4 | 上传文档后，父块进入 SQLite | SQLite chunks 表中有 `type='parent'` 的记录 |
| F5 | 子块 ChromaDB metadata 含 `parent_id` | `collection.peek()` 确认 metadata 字段 |
| F6 | RRF 融合正常 | 用含明显关键词的 query 测试，BM25 结果应出现在最终融合列表中 |
| F7 | CrossEncoder 重排 | 重排后的 Top-3 与单纯向量结果不同（用测试验证） |
| F8 | 最终输出使用父块长文本（≥1500 chars） | 检查 vectorMatches 中任意 match 的 contentPreview 长度 |
| F9 | 同一父块下的多个子块命中时只出现一次 | 强制测试（手动构造两个子块对应同一父块的场景） |
| F10 | Ingestion + Query 全链路 200 响应 | `POST /agent/run` 返回 `status: "succeeded"` |

### 4.2 性能验收

| # | 验收项 | 标准 |
|---|--------|------|
| P1 | 模型加载时间 | 启动后 10s 内完成（从缓存读取） |
| P2 | BM25 add 时间 | 单次全量重建 < 10ms（当前数据量） |
| P3 | BM25 search 时间 | < 5ms |
| P4 | 全链路 Query 时间 | 与改动前相比增加不超过 200ms（CrossEncoder predict 是瓶颈） |

### 4.3 并发安全验收

| # | 验收项 | 标准 |
|---|--------|------|
| S1 | BM25 add + search 并发 | 用 `concurrent.futures.ThreadPoolExecutor` 同时提交 10 个 add + 10 个 search，无崩溃、无数据竞争 |
| S2 | Ingestion + Query 同时进行 | 上传文档的同时执行 Query，BM25 索引正确反映最新状态 |

---

## 5. 代码质量与安全红线

### 5.1 必须遵守

| 规则 | 说明 |
|------|------|
| **类型注解** | 所有新函数/方法必须带完整类型注解 |
| **无全局变量** | 除了 `app.main.app_state`（FastAPI 标准做法），不允许在其他模块使用 `global` |
| **无 init 中的重逻辑** | `__init__` 只做赋值，不做模型加载、网络请求、文件 I/O |
| **依赖注入** | `RagQueryService` 的全局模型通过构造函数注入，不要硬引用 `app.main.app_state` |
| **日志** | 每个步骤必须打日志（参考现有代码中 `logger.info` 的模式） |
| **异常链** | `raise ... from exc` 保留异常链，不允许吞异常 |
| **与现有代码风格一致** | 命名风格、缩进、引号、import 组织方式必须与同目录下的现有文件一致 |

### 5.2 安全红线（一票否决）

| 红线 | 后果 |
|------|------|
| `try: ... except: pass` 吞异常 | ❌ 一票否决 |
| 模型文件路径硬编码 | ❌ 一票否决（必须从配置读） |
| 在请求处理函数中 import `sentence_transformers` | ❌ 一票否决（必须在启动时加载） |
| BM25 add/search 不加锁 | ❌ 一票否决 |
| 暴露 API key 或敏感配置到前端 | ❌ 一票否决 |

### 5.3 需要增加的依赖

```bash
# 安装 rank_bm25 和 jieba
pip install rank_bm25 jieba
```

`sentence-transformers` 和 `torch` 应已存在。如果缺失：

```bash
pip install sentence-transformers
```

安装后需要确认模型缓存存在：

```python
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("shibing624/text2vec-base-chinese")  # 本地缓存读取，不应联网
```

---

## 6. 测试要求

### 6.1 单元测试

| 测试 | 文件 | 说明 |
|------|------|------|
| `test_bm25_indexer.py` | `tests/` | 测试 rebuild、add、search 基本功能 |
| `test_bm25_concurrency.py` | `tests/` | 多线程并发 add + search |
| `test_rrf_fusion.py` | `tests/` | 验证 RRF 排序正确性 |
| `test_dual_chunking.py` | `tests/` | 验证 DocumentAwareChunker.dual_split() 输出 |

### 6.2 集成测试

| 测试 | 说明 |
|------|------|
| 全链路上传 → 检索 | 上传一个 .txt 文件 → 等待 ingestion 完成 → 用相关关键词 query → 检查 parent 长文本返回 |
| 并发 ingestion + query | 在 ingestion 进行中同时发起 query，确保不崩溃 |

### 6.3 回归测试

必须运行现有测试套件：

```bash
cd rag-backend
python -m pytest tests/ -v
```

现有测试不得因本次改动而失败。

---

## 7. 常见陷阱 & 决策备忘

### 7.1 已知陷阱

| 陷阱 | 避免方式 |
|------|----------|
| `rank_bm25` 的 `BM25Okapi.get_top_n` 返回的是**原文**而非索引 | 确保 `doc_pool` 和返回值类型匹配 |
| `CrossEncoder.predict()` 输入格式 | 接收 `list[tuple[str, str]]`，不是两个独立 list |
| `SentenceTransformer.encode()` 输出是 numpy 数组 | 需要 `.tolist()` 才能传给 ChromaDB |
| Lifespan 在 `--reload` 模式下会执行两次 | 这是 FastAPI 已知行为，不影响功能，但日志可能重复 |
| ChromaDB metadata 的 `parent_id` 值超长 | 确保不超过 ChromaDB 的 metadata 字段长度限制 |
| CrossEncoder 模型加载时可能 OOM | 如果内存不足，考虑使用 `device='cpu'` 或 `model_kwargs={'max_length': 512}` |

### 7.2 决策备忘 — 遇到不确定的事怎么办

| 场景 | 做法 |
|------|------|
| SQLite 表结构需要改 | **记录问题**到 `DECISIONS.md`，不要自己加字段。写清楚需要什么字段、什么类型 |
| 现有 `_expand_parent_context` 和新的 parent 捞取冲突 | 先保留旧的邻居合并作为兜底，新的 parent 捞取作为主路径 |
| `app_state` 传递方式 | 通过 `dependencies.py` 的 Depends 注入，不要直接 import `app.main` |
| BM25 停用词表不完善 | 目前的停用词表可接受。后续可由业务方维护 |
| 父块和子块的 chunk_size 精确值 | 父块 1500-2000，子块 300。验收人允许 ±20% 浮动 |
| Parent 分配策略 | 用 `chunk_index` 范围比例分配（见上面代码）。如果文本内容不连续，可以考虑基于文本 overlap 分配 |

---

## 附录 A：验证 checklist（验收人用）

```markdown
- [ ] F1: Lifespan 日志打印模型加载
- [ ] F2: BM25 search 返回非空
- [ ] F3: 三路存储同步
- [ ] F4: parent chunks 存入 SQLite
- [ ] F5: child metadata 含 parent_id
- [ ] F6: RRF 融合包含 BM25 结果
- [ ] F7: CrossEncoder 重排生效
- [ ] F8: 最终输出为长文本（≥1500 chars）
- [ ] F9: 同 parent 去重
- [ ] F10: 全链路 200
- [ ] P2: BM25 add < 10ms
- [ ] P3: BM25 search < 5ms
- [ ] S1: 并发安全测试通过
- [ ] S2: Ingestion+Query 并发不崩溃
- [ ] 现有测试全部通过
- [ ] 无 `try: except: pass`
- [ ] 无 import 在请求处理中
- [ ] BM25 加锁实现正确
```

---

*本指南由上一个会话的 AI 验收人编写。工作完成后，通知验收人进行最终审查。*
