import threading

import jieba
from rank_bm25 import BM25Okapi


class MemoryBM25Indexer:
    def __init__(self) -> None:
        self._doc_pool: list[str] = []
        self._bm25: BM25Okapi | None = None
        self._lock = threading.Lock()
        self._k1: float = 1.8
        self._b: float = 0.4
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

    def _tokenize(self, text: str) -> list[str]:
        return [w for w in jieba.cut(text) if w.strip() and w not in self._stopwords]

    def rebuild(self, chunks: list[str]) -> None:
        tokenized = [self._tokenize(d) for d in chunks]
        self._doc_pool = list(chunks)
        self._bm25 = BM25Okapi(tokenized, k1=self._k1, b=self._b)

    def add(self, text: str) -> None:
        with self._lock:
            self._doc_pool.append(text)
            tokenized = [self._tokenize(d) for d in self._doc_pool]
            self._bm25 = BM25Okapi(tokenized, k1=self._k1, b=self._b)

    def remove(self, text: str) -> None:
        with self._lock:
            self._doc_pool = [d for d in self._doc_pool if d != text]
            if not self._doc_pool:
                self._bm25 = None
                return
            tokenized = [self._tokenize(d) for d in self._doc_pool]
            self._bm25 = BM25Okapi(tokenized, k1=self._k1, b=self._b)

    def search(self, query: str, top_n: int = 10) -> list[str]:
        with self._lock:
            if not self._bm25 or not self._doc_pool:
                return []
            return self._bm25.get_top_n(self._tokenize(query), self._doc_pool, n=top_n)


def rrf_fusion(
    vector_results: list[dict],
    bm25_results: list[str],
    k: int = 60,
) -> list[dict]:
    seen: dict[str, tuple[float, dict]] = {}

    for rank, item in enumerate(vector_results):
        cid = item.get("id", "")
        text = item.get("contentPreview", "")
        score = 1.0 / (k + rank + 1)
        seen[cid] = (score, item)

    for rank, text in enumerate(bm25_results):
        matched = False
        for cid, (existing_score, item) in seen.items():
            if item.get("contentPreview") == text:
                seen[cid] = (existing_score + 1.0 / (k + rank + 1), item)
                matched = True
                break
        if not matched:
            seen[f"bm25_{rank}"] = (
                1.0 / (k + rank + 1),
                {"id": f"bm25_{rank}", "contentPreview": text, "metadata": {}},
            )

    sorted_items = sorted(seen.values(), key=lambda x: x[0], reverse=True)
    return [item for _, item in sorted_items]
