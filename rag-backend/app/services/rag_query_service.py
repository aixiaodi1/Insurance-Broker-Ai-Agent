import copy
import hashlib
import re
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from app.infrastructure.embeddings.base import EmbeddingProvider
from app.infrastructure.generators.base import AnswerGenerator
from app.infrastructure.rerankers.base import Reranker
from app.infrastructure.repositories.base import Repository
from app.infrastructure.vectorstores.base import VectorStore
from app.observability import get_logger
from app.retrieval.bm25_indexer import MemoryBM25Indexer, rrf_fusion

logger = get_logger(__name__)


class RagQueryService:
    def __init__(
        self,
        embedder: EmbeddingProvider,
        vector_store: VectorStore,
        generator: AnswerGenerator,
        reranker: Reranker | None = None,
        repository: Repository | None = None,
        cross_encoder: object | None = None,
        bm25_indexer: MemoryBM25Indexer | None = None,
        llm_provider: str = "llm",
        retrieval_top_k: int = 20,
        rerank_top_k: int = 5,
        embedding_dimension: int = 768,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._generator = generator
        self._reranker = reranker
        self._repository = repository
        self._cross_encoder = cross_encoder
        self._bm25_indexer = bm25_indexer
        self._llm_provider = llm_provider
        self._retrieval_top_k = retrieval_top_k
        self._rerank_top_k = rerank_top_k
        self._embedding_dimension = embedding_dimension
        self._cache: dict[str, dict] = {}
        self._cache_max_size = 100

    def run(self, prompt: str, collection: str, agent_id: str, thread_id: str | None) -> dict:
        run_id = f"run_{uuid4().hex}"
        started_at = datetime.now(UTC).isoformat()
        timer = perf_counter()
        events: list[dict] = []
        nodes: list[dict] = []

        logger.info(
            "rag_query_started",
            extra={"extra_fields": {"run_id": run_id, "prompt": prompt[:200], "collection": collection}},
        )

        step_start = perf_counter()
        query = prompt.strip()
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "receive_input", "Receive input", started_at, query, {"prompt": query, "durationMs": step_elapsed_ms})

        cache_key = self._cache_key(query, collection)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("cache_hit", extra={"extra_fields": {"run_id": run_id, "cache_key": cache_key}})
            response = copy.deepcopy(cached)
            response["id"] = run_id
            response["startedAt"] = started_at
            response["finishedAt"] = datetime.now(UTC).isoformat()
            response["latencyMs"] = int((perf_counter() - timer) * 1000)
            return response

        step_start = perf_counter()
        intent = self._analyze_intent(query)
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "analyze_intent", "Analyze intent", started_at, intent["summary"], {**intent, "durationMs": step_elapsed_ms})

        logger.info(
            "rag_intent_analyzed",
            extra={"extra_fields": {"run_id": run_id, "intent_query": intent["query"][:200], "duration_ms": step_elapsed_ms}},
        )

        step_start = perf_counter()
        query_embedding = self._embedder.embed_texts([intent["query"]])[0]
        if not query_embedding or len(query_embedding) == 0:
            raise ValueError("嵌入结果为空，请检查 embedding 服务")
        if len(query_embedding) != self._embedding_dimension:
            raise ValueError(f"嵌入维度异常: 期望 {self._embedding_dimension}，实际 {len(query_embedding)}")
        raw_matches = self._vector_store.query_chunks(collection, query_embedding, n_results=self._retrieval_top_k)
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(
            nodes, events, run_id, "retrieve_context", "Retrieve context", started_at,
            f"Retrieved {len(raw_matches)} chunks from Chroma collection '{collection}'. ({step_elapsed_ms}ms)",
            {"matchCount": len(raw_matches), "collection": collection, "durationMs": step_elapsed_ms},
            event_type="retrieval",
        )

        logger.info(
            "rag_retrieve_completed",
            extra={"extra_fields": {"run_id": run_id, "match_count": len(raw_matches), "duration_ms": step_elapsed_ms}},
        )

        if not raw_matches:
            final_answer = "知识库中没有足够依据回答这个问题。"
            finished_at = datetime.now(UTC).isoformat()
            latency_ms = int((perf_counter() - timer) * 1000)
            self._append_step(nodes, events, run_id, "final_answer", "Final answer", finished_at, final_answer,
                              {"finalAnswer": final_answer, "durationMs": 0, "totalMs": latency_ms}, event_type="final_answer")
            response = self._build_response(
                run_id=run_id, prompt=prompt, agent_id=agent_id, thread_id=thread_id,
                collection=collection, started_at=started_at, finished_at=finished_at,
                latency_ms=latency_ms, nodes=nodes, events=events,
                vector_matches=[], final_answer=final_answer, tokens=None, generator_raw={},
            )
            if len(self._cache) >= self._cache_max_size:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = response
            return response

        vector_matches = [_serialize_vector_match(match, index, collection) for index, match in enumerate(raw_matches)]

        if self._cross_encoder is not None and self._bm25_indexer is not None and self._repository is not None:
            vector_matches = self._run_dual_pipeline(intent["query"], vector_matches, collection)
        else:
            vector_matches = self._run_legacy_pipeline(
                intent["query"],
                vector_matches,
                collection,
                nodes,
                events,
                run_id,
                started_at,
            )

        if not vector_matches:
            final_answer = "知识库中没有足够依据回答这个问题。"
            finished_at = datetime.now(UTC).isoformat()
            latency_ms = int((perf_counter() - timer) * 1000)
            self._append_step(nodes, events, run_id, "final_answer", "Final answer", finished_at, final_answer,
                              {"finalAnswer": final_answer, "durationMs": 0, "totalMs": latency_ms}, event_type="final_answer")
            response = self._build_response(
                run_id=run_id, prompt=prompt, agent_id=agent_id, thread_id=thread_id,
                collection=collection, started_at=started_at, finished_at=finished_at,
                latency_ms=latency_ms, nodes=nodes, events=events,
                vector_matches=[], final_answer=final_answer, tokens=None, generator_raw={},
            )
            if len(self._cache) >= self._cache_max_size:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = response
            return response

        step_start = perf_counter()
        packed_context = self._pack_context(vector_matches)
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "pack_context", "Pack context", started_at,
                          f"Packed {len(vector_matches)} cited chunks. ({step_elapsed_ms}ms)",
                          {"context": packed_context, "durationMs": step_elapsed_ms})

        step_start = perf_counter()
        generation_prompt = self._build_generation_prompt(intent["query"], packed_context)
        generation = self._generator.generate(generation_prompt)
        final_answer = str(generation["answer"])
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "generate_answer", "Generate answer", started_at,
                          f"Generated answer with {self._llm_provider}. ({step_elapsed_ms}ms)",
                          {"finalAnswer": final_answer, "durationMs": step_elapsed_ms})

        step_start = perf_counter()
        citation_payload = self._verify_citations(final_answer, len(vector_matches))
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "verify_citations", "Verify citations", started_at,
                          f"{citation_payload['summary']} ({step_elapsed_ms}ms)",
                          {**citation_payload, "durationMs": step_elapsed_ms})

        finished_at = datetime.now(UTC).isoformat()
        latency_ms = int((perf_counter() - timer) * 1000)
        self._append_step(nodes, events, run_id, "final_answer", "Final answer", finished_at, final_answer,
                          {"finalAnswer": final_answer, "durationMs": 0, "totalMs": latency_ms}, event_type="final_answer")

        response = self._build_response(
            run_id=run_id, prompt=prompt, agent_id=agent_id, thread_id=thread_id,
            collection=collection, started_at=started_at, finished_at=finished_at,
            latency_ms=latency_ms, nodes=nodes, events=events,
            vector_matches=vector_matches, final_answer=final_answer,
            tokens=generation.get("tokens") if isinstance(generation.get("tokens"), dict) else None,
            generator_raw=generation.get("raw") if isinstance(generation.get("raw"), dict) else {},
        )
        if len(self._cache) >= self._cache_max_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = response
        return response

    def _run_dual_pipeline(self, query: str, vector_matches: list[dict], collection: str) -> list[dict]:
        step_start = perf_counter()

        bm25_texts = self._bm25_indexer.search(query, top_n=self._retrieval_top_k)

        step_elapsed_ms = int((perf_counter() - step_start) * 1000)

        fused = rrf_fusion(vector_matches, bm25_texts, k=60)

        if not fused:
            return []

        pairs = [(query, item["contentPreview"]) for item in fused]
        scores = self._cross_encoder.predict(pairs)
        scored = list(zip(fused, scores))
        scored.sort(key=lambda x: float(x[1]), reverse=True)
        top_k = scored[:self._rerank_top_k]

        seen_parents: set[str] = set()
        final_contexts: list[dict] = []
        for item, score in top_k:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            parent_id = metadata.get("parent_id")
            if not parent_id or parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            parent_text = self._repository.get_parent_chunk(parent_id)
            if parent_text:
                final_contexts.append({
                    **item,
                    "contentPreview": parent_text,
                    "score": float(score),
                    "metadata": {**metadata, "parent_strategy": "parent_child", "parent_id": parent_id},
                })
            else:
                fallback = self._expand_single_parent_context(collection, item)
                if fallback:
                    final_contexts.append({**fallback, "score": float(score)})

        if not final_contexts:
            for item, score in top_k:
                fallback = self._expand_single_parent_context(collection, item)
                if fallback:
                    final_contexts.append({**fallback, "score": float(score)})

        return final_contexts

    def _run_legacy_pipeline(
        self,
        query: str,
        vector_matches: list[dict],
        collection: str,
        nodes: list[dict],
        events: list[dict],
        run_id: str,
        started_at: str,
    ) -> list[dict]:
        step_start = perf_counter()
        documents = [match["contentPreview"] for match in vector_matches]
        reranked = self._reranker.rerank(query, documents, top_k=self._rerank_top_k)
        vector_matches = [
            {**vector_matches[item["index"]], "score": item["score"]}
            for item in reranked
        ]
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "rerank_context", "Rerank context", started_at,
                          f"Reranked {len(vector_matches)} chunks. ({step_elapsed_ms}ms)",
                          {"scores": [{"id": match["id"], "score": match.get("score")} for match in vector_matches], "durationMs": step_elapsed_ms},
                          event_type="retrieval")

        logger.info(
            "rag_rerank_completed",
            extra={"extra_fields": {"reranked_count": len(vector_matches), "duration_ms": step_elapsed_ms}},
        )

        step_start = perf_counter()
        vector_matches = self._expand_parent_context(collection, vector_matches)
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "expand_parent_context", "Expand parent context", started_at,
                          f"Expanded {len(vector_matches)} reranked chunks with neighboring parent context. ({step_elapsed_ms}ms)",
                          {"expandedMatches": [{"id": match["id"], "expandedFromIds": match.get("metadata", {}).get("expanded_from_ids", [match["id"]])} for match in vector_matches], "durationMs": step_elapsed_ms},
                          event_type="retrieval")

        return vector_matches

    def _expand_single_parent_context(self, collection: str, match: dict) -> dict | None:
        get_chunks_by_ids = getattr(self._vector_store, "get_chunks_by_ids", None)
        if not callable(get_chunks_by_ids):
            return None
        metadata = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
        document_id = metadata.get("document_id") or _document_id_from_chunk_id(match["id"])
        chunk_index = metadata.get("chunk_index")
        if document_id is None or not isinstance(chunk_index, int):
            return None
        wanted_ids = _neighbor_chunk_ids(str(document_id), chunk_index, match["contentPreview"])
        fetched_chunks = get_chunks_by_ids(collection, wanted_ids)
        return _merge_parent_context(match, fetched_chunks)

    def _cache_key(self, prompt: str, collection: str) -> str:
        return hashlib.md5(f"{prompt}:{collection}".encode()).hexdigest()

    def _analyze_intent(self, prompt: str) -> dict:
        return {"query": prompt, "requiresKnowledgeBase": True, "summary": "Use the original question as the retrieval query."}

    def _pack_context(self, matches: list[dict]) -> str:
        sections = []
        for index, match in enumerate(matches, start=1):
            metadata = match["metadata"]
            source_file = metadata.get("source_file") or match["title"]
            section = metadata.get("section_title") or metadata.get("clause_title") or "unknown section"
            chunk_index = metadata.get("chunk_index", "unknown")
            sections.append(f"[{index}] {source_file} / {section} / chunk {chunk_index}\n{match['contentPreview']}")
        return "\n\n".join(sections)

    def _expand_parent_context(self, collection: str, matches: list[dict]) -> list[dict]:
        get_chunks_by_ids = getattr(self._vector_store, "get_chunks_by_ids", None)
        if not callable(get_chunks_by_ids):
            return matches
        expanded_matches = []
        for match in matches:
            metadata = match["metadata"] if isinstance(match.get("metadata"), dict) else {}
            document_id = metadata.get("document_id") or _document_id_from_chunk_id(match["id"])
            chunk_index = metadata.get("chunk_index")
            if document_id is None or not isinstance(chunk_index, int):
                expanded_matches.append(match)
                continue
            wanted_ids = _neighbor_chunk_ids(str(document_id), chunk_index, match["contentPreview"])
            fetched_chunks = get_chunks_by_ids(collection, wanted_ids)
            expanded_matches.append(_merge_parent_context(match, fetched_chunks))
        return expanded_matches

    def _build_generation_prompt(self, query: str, packed_context: str) -> str:
        return (
            "请基于以下知识库资料回答问题。\n"
            "要求：\n"
            "1. 只能使用资料中的信息。\n"
            "2. 每个关键结论都要带 [1]、[2] 这样的引用。\n"
            "3. 如果资料不足，请直接说明\"知识库中没有足够依据\"。\n\n"
            f"问题：{query}\n\n"
            f"知识库资料：\n{packed_context}"
        )

    def _verify_citations(self, answer: str, context_count: int) -> dict:
        cited = sorted({int(value) for value in re.findall(r"\[(\d+)\]", answer)})
        valid = [value for value in cited if 1 <= value <= context_count]
        invalid = [value for value in cited if value not in valid]
        missing = not valid
        summary = "Citations verified." if valid and not invalid else "Answer has missing or invalid citations."
        return {"validCitationIds": valid, "invalidCitationIds": invalid, "missingCitations": missing, "summary": summary}

    def _append_step(self, nodes, events, run_id, node_id, label, timestamp, detail, payload, event_type="state_update"):
        if nodes is None:
            return
        duration_ms = payload.get("durationMs", 0)
        nodes.append({"id": node_id, "label": label, "status": "succeeded", "startedAt": timestamp,
                       "finishedAt": timestamp, "durationMs": duration_ms, "stateSummary": detail})
        events.append({"id": f"{run_id}_evt_{node_id}", "nodeId": node_id, "type": event_type,
                        "timestamp": timestamp, "title": label, "detail": detail, "payload": payload})

    def _build_response(self, run_id, prompt, agent_id, thread_id, collection, started_at, finished_at,
                        latency_ms, nodes, events, vector_matches, final_answer, tokens, generator_raw):
        request_json = {"prompt": prompt, "agentId": agent_id, "threadId": thread_id,
                         "vectorProvider": "chroma", "collection": collection, "debug": True}
        response = {"id": run_id, "mode": "real", "prompt": prompt, "status": "succeeded",
                     "startedAt": started_at, "finishedAt": finished_at, "latencyMs": latency_ms,
                     "nodes": nodes, "events": events, "toolCalls": [], "vectorMatches": vector_matches,
                     "requestJson": request_json, "responseJson": {"collection": collection,
                     "vectorProvider": "chroma", "matchCount": len(vector_matches),
                     "generator": self._llm_provider, "generatorRaw": generator_raw},
                     "finalAnswer": final_answer}
        if tokens is not None:
            response["tokens"] = tokens
        return response


def _serialize_vector_match(match: dict, index: int, collection: str) -> dict:
    metadata = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
    distance = match.get("distance")
    score = None if distance is None else max(0.0, 1.0 - float(distance))
    title = metadata.get("section_title") or metadata.get("clause_title") or metadata.get("source_file") or f"Chroma chunk {index + 1}"
    return {"id": str(match.get("id") or f"vec_{index + 1}"), "nodeId": "retrieve_context",
             "provider": "chroma", "collection": collection, "score": score, "title": str(title),
             "contentPreview": str(match.get("document") or "")[:1200], "metadata": metadata}


def _document_id_from_chunk_id(chunk_id: str) -> str | None:
    if ":" not in chunk_id:
        return None
    return chunk_id.rsplit(":", 1)[0]


def _neighbor_chunk_ids(document_id: str, chunk_index: int, text: str) -> list[str]:
    offsets = [0, 1, 2]
    if not _starts_with_numbered_heading(text):
        offsets.insert(0, -1)
    return [f"{document_id}:{chunk_index + offset}" for offset in offsets if chunk_index + offset >= 0]


def _merge_parent_context(match: dict, fetched_chunks: list[dict]) -> dict:
    by_id = {match["id"]: match}
    for chunk in fetched_chunks:
        if isinstance(chunk.get("id"), str):
            by_id[chunk["id"]] = {"id": chunk["id"], "contentPreview": str(chunk.get("document") or ""),
                                    "metadata": chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}}
    ordered = sorted(by_id.values(), key=_chunk_sort_key)
    current_index = match.get("metadata", {}).get("chunk_index")
    selected = []
    for item in ordered:
        item_index = item.get("metadata", {}).get("chunk_index")
        if item["id"] != match["id"] and isinstance(item_index, int) and isinstance(current_index, int):
            if item_index > current_index and _starts_with_numbered_heading(item["contentPreview"]):
                continue
        selected.append(item)
    merged_text = "\n".join(item["contentPreview"].strip() for item in selected if item["contentPreview"].strip())
    expanded_ids = [item["id"] for item in selected]
    if len(expanded_ids) <= 1:
        return match
    return {**match, "contentPreview": merged_text[:4000],
             "metadata": {**match["metadata"], "parent_strategy": "neighbor_window", "expanded_from_ids": expanded_ids}}


def _chunk_sort_key(match: dict) -> tuple[int, str]:
    chunk_index = match.get("metadata", {}).get("chunk_index")
    return (chunk_index if isinstance(chunk_index, int) else 0, str(match.get("id") or ""))


def _starts_with_numbered_heading(text: str) -> bool:
    return re.match(r"^\s*\d+(?:\.\d+)+\s+", text) is not None
