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
from app.services.thread_state_store import ThreadStateStore
from app.services.rule_extractor import extract_rules, get_all_required_vars
from app.services.var_extractor import extract_user_vars
from app.services.calculator import calc_reimbursement
from app.services.prompt_registry import PromptRegistry, get_default_prompt_registry

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
        state_store: ThreadStateStore | None = None,
        redis_url: str = "",
        prompt_registry: PromptRegistry | None = None,
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
        self._state_store = state_store
        self._redis_url = redis_url
        self._prompt_registry = prompt_registry or get_default_prompt_registry()

    def run(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str = "default",
        collected_vars: dict | None = None,
    ) -> dict:
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

        if intent.get("intent") != "claim_calculation" and thread_id:
            try:
                pending_state = self._state_store.get_state(user_id, thread_id, collection) if self._state_store else None
                if pending_state and pending_state.get("pending_intent") == "claim_calculation":
                    intent = {
                        **intent,
                        "intent": "claim_calculation",
                        "summary": "Continuing previous claim calculation from thread state.",
                    }
            except Exception:
                pass
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

        # --- CLAIM_CALCULATION special flow ---
        if intent.get("intent") == "claim_calculation":
            return self._run_claim_calculation(
                prompt=prompt, collection=collection, agent_id=agent_id,
                thread_id=thread_id, user_id=user_id,
                collected_vars=collected_vars or {},
                vector_matches=vector_matches, intent=intent,
                run_id=run_id, started_at=started_at, timer=timer,
                events=events, nodes=nodes, cache_key=cache_key,
            )

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
        citation_payload = self._verify_citations(final_answer, len(vector_matches), vector_matches)
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

    def _run_claim_calculation(
        self,
        prompt: str,
        collection: str,
        agent_id: str,
        thread_id: str | None,
        user_id: str,
        collected_vars: dict,
        vector_matches: list[dict],
        intent: dict,
        run_id: str,
        started_at: str,
        timer: float,
        events: list[dict],
        nodes: list[dict],
        cache_key: str,
    ) -> dict:
        calc_debug: dict[str, object] = {}

        step_start = perf_counter()
        packed_context = self._pack_context(vector_matches)
        self._append_step(nodes, events, run_id, "pack_context", "Pack context", started_at,
                          f"Packed {len(vector_matches)} cited chunks.",
                          {"context": packed_context, "durationMs": int((perf_counter() - step_start) * 1000)})
        calc_debug["pack_context_ms"] = int((perf_counter() - step_start) * 1000)

        step_start = perf_counter()
        rules = extract_rules(packed_context, self._generator)
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "extract_rules", "Extract rules", started_at,
                          f"Extracted {len(rules)} rule(s). ({step_elapsed_ms}ms)",
                          {"ruleCount": len(rules), "rules": rules, "durationMs": step_elapsed_ms})
        calc_debug["rules"] = rules
        calc_debug["extract_rules_ms"] = step_elapsed_ms

        step_start = perf_counter()
        new_vars = extract_user_vars(prompt, self._generator)
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "extract_user_vars", "Extract user vars", started_at,
                          f"Extracted {len(new_vars)} variable(s). ({step_elapsed_ms}ms)",
                          {"newVars": new_vars, "durationMs": step_elapsed_ms})
        calc_debug["new_vars"] = new_vars
        calc_debug["extract_vars_ms"] = step_elapsed_ms

        step_start = perf_counter()
        merged_state = self._merge_calculation_state(
            thread_id=thread_id,
            user_id=user_id,
            collection=collection,
            new_vars=new_vars,
            collected_vars=collected_vars,
            rules=rules,
            intent=intent,
        )
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "merge_state", "Merge thread state", started_at,
                          f"Merged {len(merged_state.get('collected_vars', {}))} var(s). ({step_elapsed_ms}ms)",
                          {"mergedState": merged_state, "durationMs": step_elapsed_ms})
        calc_debug["merged_state"] = merged_state
        calc_debug["merge_state_ms"] = step_elapsed_ms

        missing_vars = merged_state.get("missing_vars", [])
        collected = merged_state.get("collected_vars", {})
        rules_list = merged_state.get("rules", rules)
        state_id = merged_state.get("state_id")
        rule_refs = merged_state.get("rule_refs", [])
        active_document_id = merged_state.get("active_document_id")
        active_product_name = merged_state.get("active_product_name")

        has_rule = merged_state.get("has_rule", False)
        pending_calculation = bool(missing_vars) or not has_rule
        calc_result: dict | None = None

        if not pending_calculation:
            step_start = perf_counter()
            calc_result = calc_reimbursement(
                expense=collected.get("eligible_expense") or collected.get("medical_expense", 0),
                deductible=collected.get("deductible", 0),
                ratio=collected.get("reimbursement_ratio", 0),
                limit=collected.get("single_limit") or collected.get("annual_limit"),
            )
            step_elapsed_ms = int((perf_counter() - step_start) * 1000)
            self._append_step(nodes, events, run_id, "compute_calculation", "Compute calculation", started_at,
                              f"Calculated: {calc_result['explanation']} ({step_elapsed_ms}ms)",
                              {**calc_result, "durationMs": step_elapsed_ms})
            calc_debug["calc_result"] = calc_result

        answer_for_sqlite = ""

        step_start = perf_counter()
        if pending_calculation:
            calc_prompt = self._build_calculation_missing_vars_prompt(
                query=prompt,
                collected_vars=collected,
                missing_vars=missing_vars,
                rules=rules_list,
                packed_context=packed_context,
            )
            generation = self._generator.generate(
                calc_prompt,
                system_prompt=self._calculation_system_prompt(),
            )
            final_answer = str(generation["answer"])
            answer_for_sqlite = final_answer
        else:
            calc_prompt = self._build_calculation_complete_prompt(
                query=prompt,
                collected_vars=collected,
                calc_result=calc_result,
                rules=rules_list,
                packed_context=packed_context,
            )
            generation = self._generator.generate(
                calc_prompt,
                system_prompt=self._calculation_system_prompt(),
            )
            final_answer = str(generation["answer"])
            answer_for_sqlite = final_answer
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        self._append_step(nodes, events, run_id, "generate_calculation_answer", "Generate answer", started_at,
                          f"Generated answer with {self._llm_provider}. ({step_elapsed_ms}ms)",
                          {"finalAnswer": final_answer, "durationMs": step_elapsed_ms})
        calc_debug["generate_ms"] = step_elapsed_ms

        step_start = perf_counter()
        citation_payload = self._verify_citations(final_answer, len(vector_matches), vector_matches)
        step_elapsed_ms = int((perf_counter() - step_start) * 1000)
        verification_payload = {**citation_payload, "durationMs": step_elapsed_ms}
        self._append_step(nodes, events, run_id, "verify_citations", "Verify citations", started_at,
                          f"{citation_payload['summary']} ({step_elapsed_ms}ms)",
                          verification_payload)
        calc_debug["verify_ms"] = step_elapsed_ms

        if self._repository is not None:
            try:
                self._repository.create_calculation_record(
                    run_id=run_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    collection=collection,
                    active_document_id=active_document_id,
                    intent="claim_calculation",
                    formula=(calc_result or {}).get("formula_expr") or (rules_list[0] if rules_list else {}).get("formula_expr"),
                    input_vars=collected,
                    missing_vars=missing_vars or None,
                    result=calc_result,
                    rule_refs=rule_refs,
                    answer=answer_for_sqlite,
                )
            except Exception as exc:
                logger.warning("save_calculation_record_failed", extra={"extra_fields": {"error": str(exc)}})

        if self._state_store is not None and thread_id:
            try:
                self._state_store.save_state(user_id, thread_id, collection, merged_state)
            except Exception as exc:
                logger.warning("save_thread_state_failed", extra={"extra_fields": {"error": str(exc)}})

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
            calculation_extra={
                "intent": "claim_calculation",
                "activeDocumentId": active_document_id,
                "activeProductName": active_product_name,
                "collectedVars": collected,
                "missingVars": missing_vars,
                "pendingCalculation": pending_calculation,
                "calculation": calc_result,
                "stateId": state_id,
            },
        )
        if len(self._cache) >= self._cache_max_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[cache_key] = response
        return response

    def _merge_calculation_state(
        self,
        thread_id: str | None,
        user_id: str,
        collection: str,
        new_vars: dict,
        collected_vars: dict,
        rules: list[dict],
        intent: dict,
    ) -> dict:
        old_state: dict | None = None
        if self._state_store is not None and thread_id:
            try:
                old_state = self._state_store.get_state(user_id, thread_id, collection)
            except Exception as exc:
                logger.warning("load_thread_state_failed", extra={"extra_fields": {"error": str(exc)}})

        old_vars: dict = {}
        old_missing: list = []
        if old_state is not None:
            old_vars = old_state.get("collected_vars", {})
            old_missing = old_state.get("missing_vars", [])

        merged: dict[str, object] = {}
        merged.update(old_vars)
        merged.update(collected_vars)
        merged.update(new_vars)

        required = get_all_required_vars(rules)
        missing = [v for v in required if v not in merged]

        state_id = None
        if thread_id:
            import hashlib
            state_id = hashlib.md5(f"{user_id}:{thread_id}:{collection}".encode()).hexdigest()[:12]

        document_id = None
        product_name = None
        if old_state:
            document_id = old_state.get("active_document_id")
            product_name = old_state.get("active_product_name")
        elif intent.get("intent") == "claim_calculation":
            document_id = f"doc_{collection}"

        rule_refs = []
        has_valid_rule = False
        for rule in rules:
            for ev in rule.get("evidence", []):
                if isinstance(ev, dict) and ev.get("chunk_id"):
                    rule_refs.append(ev)
            if rule.get("required_vars") and rule.get("rule_type") != "unknown":
                has_valid_rule = True

        return {
            "thread_id": thread_id,
            "user_id": user_id,
            "collection": collection,
            "active_document_id": document_id,
            "active_product_name": product_name,
            "pending_intent": "claim_calculation",
            "collected_vars": merged,
            "missing_vars": missing,
            "rule_refs": rule_refs,
            "rules": rules,
            "has_rule": has_valid_rule,
            "pending_calculation": bool(missing) or not has_valid_rule,
            "state_id": state_id,
        }

    def _build_calculation_missing_vars_prompt(
        self,
        query: str,
        collected_vars: dict,
        missing_vars: list[str],
        rules: list[dict],
        packed_context: str,
    ) -> str:
        var_names = {
            "medical_expense": "医疗费用",
            "eligible_expense": "可赔费用",
            "deductible": "免赔额",
            "reimbursement_ratio": "赔付比例",
            "social_insurance_used": "是否经社保结算",
            "annual_limit": "年度限额",
            "single_limit": "单次限额",
            "hospital_level": "医院等级",
            "disease_name": "疾病名称",
            "claim_type": "理赔类型",
        }
        has_valid_rule = any(
            r.get("required_vars") and r.get("rule_type") != "unknown"
            for r in rules
        )
        if not has_valid_rule:
            return self._prompt_registry.render(
                "claim_calculation_no_rule",
                query=query,
                packed_context=packed_context,
            ).user
        known_lines = "\n".join(
            f"- {var_names.get(k, k)}：{v}" for k, v in collected_vars.items()
        )
        missing_lines = "\n".join(
            f"- {var_names.get(v, v)}" for v in missing_vars
        )
        formula = rules[0].get("formula", "") if rules else ""
        return self._prompt_registry.render(
            "claim_calculation_missing_vars",
            query=query,
            packed_context=packed_context,
            formula=formula,
            known_lines=known_lines if known_lines else "(暂无)",
            missing_lines=missing_lines if missing_lines else "(暂无)",
        ).user

    def _build_calculation_complete_prompt(
        self,
        query: str,
        collected_vars: dict,
        calc_result: dict | None,
        rules: list[dict],
        packed_context: str,
    ) -> str:
        calculation_text = ""
        if calc_result:
            calculation_text = (
                f"后端计算结果：\n"
                f"- 公式：{calc_result.get('explanation', '')}\n"
                f"- 计算结果：{calc_result.get('result', '')} 元\n\n"
            )
        return self._prompt_registry.render(
            "claim_calculation_complete",
            query=query,
            packed_context=packed_context,
            calculation_text=calculation_text,
        ).user

    def _calculation_system_prompt(self) -> str:
        return self._prompt_registry.render("claim_calculation_system").system or ""

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
        return self._prompt_registry.render(
            "rag_clause_qa",
            query=query,
            packed_context=packed_context,
        ).user

    def _check_citation_article_mismatch(self, answer: str, vector_matches: list[dict]) -> list[dict]:
        mismatches: list[dict] = []
        section_titles: dict[int, str] = {}
        for idx, m in enumerate(vector_matches, start=1):
            meta = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
            title = meta.get("section_title") or meta.get("clause_title") or ""
            section_titles[idx] = title

        for ref_num, title in section_titles.items():
            expected_no = _extract_article_number(title)
            if expected_no is None:
                continue
            answer_lines = answer.split("\n")
            for line in answer_lines:
                if f"[{ref_num}]" not in line:
                    continue
                mentioned = re.findall(r"第[一二三四五六七八九十\d]+条", line)
                if not mentioned:
                    continue
                actual_numbers = set()
                for m in mentioned:
                    n = _chinese_to_arabic(m)
                    if n is not None:
                        actual_numbers.add(n)
                if actual_numbers and expected_no not in actual_numbers:
                    mismatches.append({
                        "citationId": ref_num,
                        "expectedArticle": expected_no,
                        "actualArticles": sorted(actual_numbers),
                        "sectionTitle": title,
                        "line": line.strip(),
                    })
        return mismatches

    def _verify_citations(self, answer: str, context_count: int, vector_matches: list[dict] | None = None) -> dict:
        cited = sorted({int(value) for value in re.findall(r"\[(\d+)\]", answer)})
        valid = [value for value in cited if 1 <= value <= context_count]
        invalid = [value for value in cited if value not in valid]
        missing = not valid
        article_mismatches = []
        if vector_matches:
            article_mismatches = self._check_citation_article_mismatch(answer, vector_matches)
        summary_parts = []
        if valid and not invalid:
            summary_parts.append("Citations verified.")
        else:
            summary_parts.append("Answer has missing or invalid citations.")
        if article_mismatches:
            summary_parts.append(f"Article number mismatches found: {len(article_mismatches)}.")
        return {
            "validCitationIds": valid,
            "invalidCitationIds": invalid,
            "missingCitations": missing,
            "articleMismatches": article_mismatches,
            "summary": " ".join(summary_parts),
        }

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
                        intent_result: dict | None = None,
                        calculation_extra: dict | None = None):
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
        if calculation_extra:
            for k, v in calculation_extra.items():
                response[k] = v
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

        citations = {}
        for idx, m in enumerate(vector_matches, start=1):
            meta = m.get("metadata") if isinstance(m.get("metadata"), dict) else {}
            citations[str(idx)] = {
                "title": m.get("title", ""),
                "sectionTitle": meta.get("section_title", ""),
                "sourceFile": meta.get("source_file", ""),
                "contentType": meta.get("content_type", ""),
            }
        response["citations"] = citations
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


_CHINESE_NUM_MAP: dict[str, int] = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _chinese_to_arabic(text: str) -> int | None:
    m = re.search(r"第([一二三四五六七八九十\d]+)条", text)
    if not m:
        return None
    num_str = m.group(1)
    if num_str.isdigit():
        return int(num_str)
    if num_str in _CHINESE_NUM_MAP:
        return _CHINESE_NUM_MAP[num_str]
    if "十" in num_str:
        parts = num_str.split("十")
        left = _CHINESE_NUM_MAP.get(parts[0], 1) if parts[0] else 1
        right = _CHINESE_NUM_MAP.get(parts[1], 0) if parts[1] else 0
        return left * 10 + right
    return None


def _extract_article_number(section_title: str) -> int | None:
    return _chinese_to_arabic(section_title)
