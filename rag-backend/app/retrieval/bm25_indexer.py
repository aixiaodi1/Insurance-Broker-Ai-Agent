import threading
from dataclasses import dataclass, field
from typing import Any

import jieba
from rank_bm25 import BM25Okapi


@dataclass
class BM25Doc:
    id: str
    text: str
    collection: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryBM25Indexer:
    def __init__(self) -> None:
        self._docs: list[BM25Doc] = []
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

    def rebuild(self, docs: list[BM25Doc | dict | str]) -> None:
        with self._lock:
            self._docs = [_to_doc(d) for d in docs]
            tokenized = [self._tokenize(d.text) for d in self._docs]
            self._bm25 = BM25Okapi(tokenized, k1=self._k1, b=self._b)

    def add(self, doc: BM25Doc | dict | str) -> None:
        with self._lock:
            d = _to_doc(doc)
            self._docs.append(d)
            tokenized = [self._tokenize(d.text) for d in self._docs]
            self._bm25 = BM25Okapi(tokenized, k1=self._k1, b=self._b)

    def remove_by_id(self, doc_id: str) -> None:
        with self._lock:
            self._docs = [d for d in self._docs if d.id != doc_id]
            if not self._docs:
                self._bm25 = None
                return
            tokenized = [self._tokenize(d.text) for d in self._docs]
            self._bm25 = BM25Okapi(tokenized, k1=self._k1, b=self._b)

    def search(
        self,
        query: str,
        top_n: int = 10,
        collection: str | None = None,
    ) -> list[dict]:
        with self._lock:
            if not self._bm25 or not self._docs:
                return []

            tokenized_query = self._tokenize(query)

            if collection is not None:
                filtered_indices = [
                    i for i, d in enumerate(self._docs)
                    if d.collection == collection
                ]
                if not filtered_indices:
                    return []
                filtered_docs = [self._docs[i] for i in filtered_indices]
                filtered_tokenized = [
                    self._tokenize(d.text) for d in filtered_docs
                ]
                temp_bm25 = BM25Okapi(
                    filtered_tokenized, k1=self._k1, b=self._b
                )
                scores = temp_bm25.get_scores(tokenized_query)
                top_indices = sorted(
                    range(len(scores)),
                    key=lambda i: scores[i],
                    reverse=True,
                )[:top_n]
                return [
                    {
                        "id": filtered_docs[i].id,
                        "contentPreview": filtered_docs[i].text,
                        "metadata": dict(filtered_docs[i].metadata),
                        "collection": filtered_docs[i].collection,
                        "bm25_rank": rank,
                        "bm25_score": float(scores[i]),
                    }
                    for rank, i in enumerate(top_indices)
                ]

            scores = self._bm25.get_scores(tokenized_query)
            top_indices = sorted(
                range(len(scores)),
                key=lambda i: scores[i],
                reverse=True,
            )[:top_n]
            return [
                {
                    "id": self._docs[i].id,
                    "contentPreview": self._docs[i].text,
                    "metadata": dict(self._docs[i].metadata),
                    "collection": self._docs[i].collection,
                    "bm25_rank": rank,
                    "bm25_score": float(scores[i]),
                }
                for rank, i in enumerate(top_indices)
            ]


def _to_doc(doc: BM25Doc | dict | str) -> BM25Doc:
    if isinstance(doc, BM25Doc):
        return doc
    if isinstance(doc, dict):
        mid = doc.get("metadata") or {}
        return BM25Doc(
            id=str(doc.get("id", "")),
            text=str(doc.get("text", doc.get("contentPreview", ""))),
            collection=str(doc.get("collection", "default")),
            metadata=dict(mid),
        )
    return BM25Doc(id=doc, text=doc, collection="default")


def rrf_fusion(
    vector_results: list[dict],
    bm25_results: list[dict],
    k: int = 60,
) -> list[dict]:
    seen: dict[str, dict] = {}

    for rank, item in enumerate(vector_results):
        cid = item.get("id", "")
        score = 1.0 / (k + rank + 1)
        seen[cid] = {
            **item,
            "rrf_score": score,
            "rrf_debug": {
                "vector_rank": rank,
                "vector_score": score,
                "bm25_rank": None,
                "bm25_score": None,
                "section_bm25_rank": None,
                "section_bm25_score": None,
            },
        }

    for rank, item in enumerate(bm25_results):
        bid = item.get("id", "")
        score = 1.0 / (k + rank + 1)

        if bid in seen:
            seen[bid]["rrf_score"] = seen[bid]["rrf_score"] + score
            seen[bid]["rrf_debug"]["bm25_rank"] = rank
            seen[bid]["rrf_debug"]["bm25_score"] = score
        else:
            seen[bid] = {
                "id": bid,
                "contentPreview": item.get("contentPreview", ""),
                "metadata": item.get("metadata", {}),
                "collection": item.get("collection", "default"),
                "rrf_score": score,
                "rrf_debug": {
                    "vector_rank": None,
                    "vector_score": None,
                    "bm25_rank": rank,
                    "bm25_score": score,
                    "section_bm25_rank": None,
                    "section_bm25_score": None,
                },
            }

    sorted_items = sorted(
        seen.values(), key=lambda x: x["rrf_score"], reverse=True
    )
    return sorted_items
