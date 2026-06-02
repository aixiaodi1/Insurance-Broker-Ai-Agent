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
from app.services.intent_classifier import classify_intent, expand_synonyms, intent_summary, content_type_hints, section_hints
from app.services.retrieval_planner import RetrievalPlanner, filter_by_content_type, dedup_matches

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
        self._planner = RetrievalPlanner()

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

        timer_embed = perf_counter()
        query_embedding = self._embedder.embed_texts([intent["query"]])[0]
        embed_ms = int((perf_counter() - timer_embed) * 1000)
        if not query_embedding or len(query_embedding) == 0:
            raise ValueError("嵌入结果为空，请检查 embedding 服务")
        if len(query_embedding) != self._embedding_dimension:
            raise ValueError(f"嵌入维度异常: 期望 {self._embedding_dimension}，实际 {len(query_embedding)}")

        timer_vq = perf_counter()
        dense_top_k = min(self._retrieval_top_k * 3, 200) if self._cross_encoder is not None else self._retrieval_top_k
        raw_matches = self._vector_store.query_chunks(collection, query_embedding, n_results=dense_top_k)
        vq_ms = int((perf_counter() - timer_vq) * 1000)
        retrieve_ms = embed_ms + vq_ms
        self._append_step(
            nodes, events, run_id, "retrieve_context", "Retrieve context", started_at,
            f"Embedded ({embed_ms}ms) + queried {len(raw_matches)} chunks from Chroma ({vq_ms}ms).",
            {"matchCount": len(raw_matches), "collection": collection, "durationMs": retrieve_ms,
             "embedMs": embed_ms, "vectorQueryMs": vq_ms},
            event_type="retrieval",
        )

        logger.info(
            "rag_retrieve_completed",
            extra={"extra_fields": {
                "run_id": run_id, "match_count": len(raw_matches),
                "embed_ms": embed_ms, "vector_query_ms": vq_ms, "total_ms": retrieve_ms,
            }},
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
                intent_result=intent,
            )
            if len(self._cache) >= self._cache_max_size:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = response
            return response

        vector_matches = [_serialize_vector_match(match, index, collection) for index, match in enumerate(raw_matches)]

        if self._bm25_indexer is not None and self._repository is not None:
            vector_matches = self._run_dual_pipeline(
                intent["query"], vector_matches, collection,
                expanded_queries=intent.get("expanded_queries"),
                intent_type=intent.get("intent"),
                nodes=nodes, events=events, run_id=run_id, started_at=started_at,
            )
        elif self._reranker is not None:
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
                intent_result=intent,
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
        packed_context_text = packed_context
        number_check = self._verify_answer_numbers(final_answer, packed_context_text)
        evidence_check = self._verify_answer_evidence(final_answer, vector_matches)
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        verification_payload = {
            **citation_payload,
            **number_check,
            **evidence_check,
            "durationMs": step_elapsed_ms,
        }
        self._append_step(nodes, events, run_id, "verify_citations", "Verify citations", started_at,
                          f"{citation_payload['summary']} ({step_elapsed_ms}ms)",
                          verification_payload)

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
            intent_result=intent,
        )
        if len(self._cache) >= self._cache_max_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = response
        return response

    def _run_dual_pipeline(
        self,
        query: str,
        vector_matches: list[dict],
        collection: str,
        expanded_queries: list[str] | None = None,
        intent_type: str | None = None,
        nodes: list | None = None,
        events: list | None = None,
        run_id: str | None = None,
        started_at: str | None = None,
    ) -> list[dict]:
        lanes = self._planner.plan(intent_type or "general", query, expanded_queries)
        lane_debug = self._planner.describe(lanes)

        if nodes is not None and run_id is not None and started_at is not None:
            self._append_step(nodes, events, run_id, "plan_retrieval", "Plan retrieval", started_at,
                              f"Planned {len(lanes)} retrieval lanes for intent={intent_type or 'general'}",
                              {"lanes": lane_debug, "durationMs": 0})

        timer_bm25 = perf_counter()
        bm25_queries = [query]
        if expanded_queries:
            for eq in expanded_queries:
                if eq != query:
                    bm25_queries.append(eq)

        section_bm25_queries = [l.query for l in lanes if l.method == "section_bm25" and l.query != query]

        all_bm25_results: list[dict] = []
        for q in bm25_queries:
            for r in self._bm25_indexer.search(q, top_n=self._retrieval_top_k, collection=collection):
                r["_bm25_source"] = "bm25"
                all_bm25_results.append(r)
        for q in section_bm25_queries:
            for r in self._bm25_indexer.search(q, top_n=self._retrieval_top_k, collection=collection):
                r["_bm25_source"] = "section_bm25"
                all_bm25_results.append(r)

        seen_ids: set[str] = set()
        bm25_texts = []
        for r in all_bm25_results:
            rid = r.get("id", "")
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            bm25_texts.append(r)
        bm25_ms = int((perf_counter() - timer_bm25) * 1000)

        dense_content_types = set()
        for l in lanes:
            if l.method == "dense" and l.target_content_types:
                dense_content_types.update(l.target_content_types)
        if dense_content_types:
            vector_matches = filter_by_content_type(vector_matches, list(dense_content_types))

        timer_rrf = perf_counter()
        weights = {l.method: l.weight for l in lanes}
        dense_weight = weights.get("dense", 1.0)
        bm25_weight = weights.get("bm25", 1.0)
        section_weight = weights.get("section_bm25", 1.5)

        weighted_rrf = self._weighted_rrf_fusion(vector_matches, bm25_texts, k=60, dense_weight=dense_weight, bm25_weight=bm25_weight, section_weight=section_weight)
        rrf_ms = int((perf_counter() - timer_rrf) * 1000)

        fused = weighted_rrf
        fused = dedup_matches(fused)

        logger.info(
            "dual_pipeline_bm25_rrf",
            extra={"extra_fields": {
                "bm25_count": len(bm25_texts),
                "fused_count": len(fused),
                "bm25_ms": bm25_ms,
                "rrf_ms": rrf_ms,
                "lanes": lane_debug,
            }},
        )

        if not fused:
            return []

        if nodes is not None and run_id is not None and started_at is not None:
            rrf_debug_info = [
                {
                    "id": item.get("id"),
                    "rrf_score": item.get("rrf_score"),
                    "rrf_debug": item.get("rrf_debug"),
                }
                for item in fused[:10]
            ]
            self._append_step(nodes, events, run_id, "fuse_retrieval", "Fuse multi-path retrieval", started_at,
                              f"Fused {len(fused)} results from {len(lanes)} lanes (RRF)",
                              {"fusionCount": len(fused), "rrfTopK": rrf_debug_info, "denseWeight": dense_weight, "bm25Weight": bm25_weight, "sectionWeight": section_weight, "durationMs": rrf_ms})

        ce_ms = 0
        rerank_ms = 0
        if self._cross_encoder is not None:
            timer_ce = perf_counter()
            pairs = [(query, item["contentPreview"]) for item in fused]
            scores = self._cross_encoder.predict(pairs)
            ce_ms = int((perf_counter() - timer_ce) * 1000)

            timer_rerank = perf_counter()
            scored = list(zip(fused, scores))
            scored.sort(key=lambda x: float(x[1]), reverse=True)
            top_k = scored[:self._rerank_top_k]
            rerank_ms = int((perf_counter() - timer_rerank) * 1000)

            logger.info(
                "dual_pipeline_crossencoder",
                extra={"extra_fields": {
                    "ce_input_count": len(pairs),
                    "ce_ms": ce_ms,
                    "rerank_ms": rerank_ms,
                    "top_k": len(top_k),
                }},
            )
        elif self._reranker is not None:
            timer_rerank = perf_counter()
            documents = [item["contentPreview"] for item in fused]
            reranked = self._reranker.rerank(query, documents, top_k=self._rerank_top_k)
            scored = [(fused[item["index"]], item["score"]) for item in reranked]
            top_k = scored[:self._rerank_top_k]
            rerank_ms = int((perf_counter() - timer_rerank) * 1000)

            logger.info(
                "dual_pipeline_reranker",
                extra={"extra_fields": {
                    "rerank_input_count": len(documents),
                    "rerank_ms": rerank_ms,
                    "top_k": len(top_k),
                }},
            )
        else:
            scored = [(item, 0.0) for item in fused[:self._rerank_top_k]]
            top_k = scored

        timer_parent = perf_counter()
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

        parent_ms = int((perf_counter() - timer_parent) * 1000)
        logger.info(
            "dual_pipeline_parent_expand",
            extra={"extra_fields": {
                "final_count": len(final_contexts),
                "parent_ms": parent_ms,
                "total_ms": bm25_ms + rrf_ms + ce_ms + rerank_ms + parent_ms,
            }},
        )

        return final_contexts

    def _weighted_rrf_fusion(
        self,
        vector_results: list[dict],
        bm25_results: list[dict],
        k: int = 60,
        dense_weight: float = 1.0,
        bm25_weight: float = 1.0,
        section_weight: float = 1.5,
    ) -> list[dict]:
        seen: dict[str, dict] = {}

        for rank, item in enumerate(vector_results):
            cid = item.get("id", "")
            score = dense_weight / (k + rank + 1)
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
            source = item.get("_bm25_source", "bm25")
            used_weight = section_weight if source == "section_bm25" else bm25_weight
            score = used_weight / (k + rank + 1)

            lane = "section_bm25" if source == "section_bm25" else "bm25"

            if bid in seen:
                seen[bid]["rrf_score"] = seen[bid]["rrf_score"] + score
                seen[bid]["rrf_debug"][f"{lane}_rank"] = rank
                seen[bid]["rrf_debug"][f"{lane}_score"] = score
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
                        "bm25_rank": rank if lane == "bm25" else None,
                        "bm25_score": score if lane == "bm25" else None,
                        "section_bm25_rank": rank if lane == "section_bm25" else None,
                        "section_bm25_score": score if lane == "section_bm25" else None,
                    },
                }

        sorted_items = sorted(seen.values(), key=lambda x: x["rrf_score"], reverse=True)
        return sorted_items

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
        context = f"{prompt}:{collection}:{self._retrieval_top_k}:{self._rerank_top_k}:{self._llm_provider}:{self._embedding_dimension}"
        return hashlib.md5(context.encode()).hexdigest()

    def _analyze_intent(self, prompt: str) -> dict:
        intent = classify_intent(prompt)
        expanded = expand_synonyms(prompt)
        return {
            "query": prompt,
            "expanded_queries": expanded,
            "requiresKnowledgeBase": True,
            "intent": intent.value,
            "summary": intent_summary(intent),
            "content_type_hints": content_type_hints(intent),
            "section_hints": section_hints(intent),
        }

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
            "你是一个严谨的保险条款分析助手，基于以下知识库资料回答问题。\n\n"
            "要求：\n"
            "1. 只能使用知识库资料中的信息，不得根据常识补充保险责任。\n"
            "2. 每个关键结论必须带 [1]、[2] 这样的引用指向资料编号。\n"
            "3. 涉及数字、百分比、年龄、次数、等待期时，必须确认该数字存在于资料中。\n"
            "4. 回答赔不赔时，必须同时考虑保险责任和责任免除条款。\n"
            "5. 回答疾病算不算时，必须基于疾病定义条款判定。\n"
            "6. 如果资料不足，直接说明「知识库中没有足够依据」。\n"
            "7. 按以下结构组织回答：\n"
            "   - 结论：简明回答\n"
            "   - 依据：引用具体条款编号和页码\n"
            "   - 注意事项：免责、年龄、等待期、次数限制\n"
            "   - 未确认信息：当前资料无法确认的部分\n\n"
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

    def _verify_answer_numbers(self, answer: str, context: str) -> dict:
        number_details: list[dict] = []
        matches = re.findall(r"(\d+(?:\.\d+)?)(?:\s*%|百分比|种|次|年|岁|天|元|万|千|百万)", answer)
        for num_str in matches:
            exists = num_str in context
            number_details.append({"number": num_str, "found_in_evidence": exists})
        return {"numbersChecked": len(number_details), "numberDetails": number_details}

    def _verify_answer_evidence(self, answer: str, context_parts: list[dict]) -> dict:
        warnings: list[str] = []
        lower_answer = answer.lower()

        liability_keywords = ["赔", "给付", "保险金", "赔付", "赔偿"]
        exclusion_keywords = ["免责", "不赔", "不承担", "除外", "不负责"]

        has_liability = any(kw in lower_answer for kw in liability_keywords)
        has_exclusion = any(kw in lower_answer for kw in exclusion_keywords)

        context_types = set()
        for part in context_parts:
            meta = part.get("metadata") or {}
            ct = meta.get("content_type", "")
            if ct:
                context_types.add(ct)

        if has_liability and "insurance_liability" not in context_types and "clause" not in context_types:
            warnings.append("Answer mentions payout but context lacks insurance_liability clauses")

        if has_exclusion and "exclusion" not in context_types:
            warnings.append("Answer mentions exclusions but context lacks exclusion clauses")

        return {"evidenceWarnings": warnings, "contextTypesPresent": list(context_types)}

    def _append_step(self, nodes, events, run_id, node_id, label, timestamp, detail, payload, event_type="state_update"):
        if nodes is None:
            return
        duration_ms = payload.get("durationMs", 0)
        nodes.append({"id": node_id, "label": label, "status": "succeeded", "startedAt": timestamp,
                       "finishedAt": timestamp, "durationMs": duration_ms, "stateSummary": detail})
        events.append({"id": f"{run_id}_evt_{node_id}", "nodeId": node_id, "type": event_type,
                        "timestamp": timestamp, "title": label, "detail": detail, "payload": payload})

    def _build_response(self, run_id, prompt, agent_id, thread_id, collection, started_at, finished_at,
                        latency_ms, nodes, events, vector_matches, final_answer, tokens, generator_raw,
                        intent_result: dict | None = None):
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
        if intent_result:
            response["intent"] = intent_result.get("intent", "general")
            response["expandedQueries"] = intent_result.get("expanded_queries", [])
            response["responseJson"]["intent"] = intent_result.get("intent", "general")
            response["responseJson"]["expandedQueries"] = intent_result.get("expanded_queries", [])
        retrieval_debug = {
            "intent": intent_result.get("intent", "general") if intent_result else "general",
            "expandedQueries": intent_result.get("expanded_queries", []) if intent_result else [],
            "finalContextCount": len(vector_matches),
            "finalContextSections": [
                {
                    "id": m.get("id"),
                    "sectionTitle": m.get("metadata", {}).get("section_title", "") if isinstance(m.get("metadata"), dict) else "",
                    "contentType": m.get("metadata", {}).get("content_type", "") if isinstance(m.get("metadata"), dict) else "",
                    "rrfScore": m.get("rrf_score"),
                }
                for m in vector_matches[:5]
            ],
        }
        response["retrievalDebug"] = retrieval_debug
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
