"""
Golden QA Eval Runner — PR-4

Usage:
    python scripts/run_eval.py [--data data/evals/golden_qa.json] [--collection default]

Runs each question through the RAG pipeline, checks retrieval coverage and
answer quality, and prints a summary table.
"""

import json
import re
import sys
from pathlib import Path
from time import perf_counter

# Add project root to sys.path so that import app works
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import Settings
from app.dependencies import build_embedder, get_answer_generator, get_repository, get_vector_store, get_bm25_indexer, get_cross_encoder, get_reranker
from app.retrieval.bm25_indexer import rrf_fusion
from app.services.rag_query_service import RagQueryService


def load_qa(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def evaluate_question(
    service: RagQueryService,
    question: dict,
    collection: str,
) -> dict:
    qid = question["id"]
    start = perf_counter()

    result = service.run(
        prompt=question["question"],
        collection=collection,
        agent_id="eval-runner",
        thread_id=f"eval-{qid}",
    )

    elapsed_s = perf_counter() - start

    answer = result.get("finalAnswer", "")
    vector_matches = result.get("vectorMatches", [])

    retrieved_sections = set()
    for match in vector_matches:
        meta = match.get("metadata") or {}
        section = meta.get("section_no") or ""
        if section:
            retrieved_sections.add(section)

    must_retrieve = set(question.get("must_retrieve", []))
    answer_contains = question.get("answer_contains", [])
    must_not_contain = question.get("must_not_contain", [])
    must_cite = question.get("must_cite_sections", [])

    recall_ok = must_retrieve.issubset(retrieved_sections) if must_retrieve else True
    answer_ok = all(kw in answer for kw in answer_contains) if answer_contains else True
    forbid_ok = not any(kw in answer for kw in must_not_contain) if must_not_contain else True

    cited_sections_found = set()
    for match in vector_matches:
        meta = match.get("metadata") or {}
        section = meta.get("section_no") or ""
        if section in must_cite:
            cited_sections_found.add(section)
    citation_ok = must_cite.issubset(cited_sections_found) if must_cite else True

    passed = recall_ok and answer_ok and forbid_ok and citation_ok

    return {
        "id": qid,
        "question": question["question"],
        "category": question.get("category", ""),
        "passed": passed,
        "recall_ok": recall_ok,
        "answer_ok": answer_ok,
        "forbid_ok": forbid_ok,
        "citation_ok": citation_ok,
        "retrieved_sections": sorted(retrieved_sections),
        "must_retrieve": sorted(must_retrieve),
        "latency_ms": result.get("latencyMs", int(elapsed_s * 1000)),
        "answer_preview": answer[:120] if answer else "(empty)",
    }


def print_results(results: list[dict]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    print(f"\n{'='*70}")
    print(f"  Golden QA Eval Results  ({passed}/{total} passed)")
    print(f"{'='*70}\n")

    print(f"{'ID':<10} {'Category':<20} {'Status':<8} {'Recall':<8} {'Ans':<8} {'Forbid':<8} {'Cite':<8} {'Latency(ms)':<12}")
    print(f"{'-'*10} {'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*12}")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"{r['id']:<10} {r['category']:<20} {status:<8} {'✓' if r['recall_ok'] else '✗':<8} {'✓' if r['answer_ok'] else '✗':<8} {'✓' if r['forbid_ok'] else '✗':<8} {'✓' if r['citation_ok'] else '✗':<8} {r['latency_ms']:<12}")

    print(f"\n{'='*70}")
    print(f"  Summary: {passed}/{total} passed ({passed/total*100:.1f}%)")

    recall_rate = sum(1 for r in results if r["recall_ok"]) / total * 100
    answer_rate = sum(1 for r in results if r["answer_ok"]) / total * 100
    forbid_rate = sum(1 for r in results if r["forbid_ok"]) / total * 100
    citation_rate = sum(1 for r in results if r["citation_ok"]) / total * 100
    avg_latency = sum(r["latency_ms"] for r in results) / total

    print(f"  Recall@5 (section-level):         {recall_rate:.1f}%")
    print(f"  Answer key-point hit rate:          {answer_rate:.1f}%")
    print(f"  Forbidden term avoidance rate:      {forbid_rate:.1f}%")
    print(f"  Citation accuracy:                  {citation_rate:.1f}%")
    print(f"  Average latency:                    {avg_latency:.0f}ms")
    print(f"{'='*70}\n")

    failed = [r for r in results if not r["passed"]]
    if failed:
        print("Failed cases:")
        for r in failed:
            flags = []
            if not r["recall_ok"]:
                flags.append(f"recall(must={r['must_retrieve']}, got={r['retrieved_sections']})")
            if not r["answer_ok"]:
                flags.append("answer_missing_keywords")
            if not r["forbid_ok"]:
                flags.append("forbidden_keywords_found")
            if not r["citation_ok"]:
                flags.append("citation_missing")
            print(f"  {r['id']}: {', '.join(flags)}")

    return {
        "total": total,
        "passed": passed,
        "recall_rate": recall_rate,
        "answer_rate": answer_rate,
        "forbid_rate": forbid_rate,
        "citation_rate": citation_rate,
        "avg_latency_ms": avg_latency,
    }


def main() -> None:
    args = _parse_args()
    qa_path = Path(args.get("data", str(_PROJECT_ROOT / "data" / "evals" / "golden_qa.json")))
    collection = args.get("collection", "default")

    questions = load_qa(qa_path)
    settings = Settings()

    embedder = build_embedder(settings)
    vector_store = get_vector_store()
    generator = get_answer_generator()
    repository = get_repository()
    cross_encoder = get_cross_encoder()
    bm25_indexer = get_bm25_indexer()

    reranker = get_reranker()
    if cross_encoder and bm25_indexer:
        service = RagQueryService(
            embedder=embedder,
            vector_store=vector_store,
            generator=generator,
            repository=repository,
            cross_encoder=cross_encoder,
            bm25_indexer=bm25_indexer,
            llm_provider=settings.llm_provider,
            retrieval_top_k=min(settings.rag_retrieval_top_k, 10),
            rerank_top_k=3,
            embedding_dimension=settings.embedding_dimension,
        )
    else:
        service = RagQueryService(
            embedder=embedder,
            vector_store=vector_store,
            generator=generator,
            reranker=reranker,
            repository=repository,
            llm_provider=settings.llm_provider,
            retrieval_top_k=settings.rag_retrieval_top_k,
            rerank_top_k=settings.rag_rerank_top_k,
            embedding_dimension=settings.embedding_dimension,
        )

    results = []
    for question in questions:
        r = evaluate_question(service, question, collection)
        results.append(r)
        print(f"  [{r['id']}] {'PASS' if r['passed'] else 'FAIL'}  {question['question'][:50]}")

    print_results(results)


def _parse_args() -> dict:
    args = {}
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--data" and i + 2 < len(sys.argv):
            args["data"] = sys.argv[i + 2]
        elif arg == "--collection" and i + 2 < len(sys.argv):
            args["collection"] = sys.argv[i + 2]
    return args


if __name__ == "__main__":
    main()
