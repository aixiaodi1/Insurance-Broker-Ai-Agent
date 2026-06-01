from app.services.rag_query_service import RagQueryService


class FakeEmbedder:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[0.1, 0.2] for _text in texts]


class FakeVectorStore:
    def __init__(self) -> None:
        self.n_results: int | None = None
        self.get_chunks_collections: list[str] = []

    def query_chunks(self, collection: str, embedding: list[float], n_results: int = 5) -> list[dict]:
        self.n_results = n_results
        return [
            {
                "id": "doc_1:0",
                "document": "Low priority context.",
                "metadata": {"source_file": "low.txt", "chunk_index": 0},
                "distance": 0.4,
            },
            {
                "id": "doc_2:0",
                "document": "High priority context with claim rules.",
                "metadata": {"source_file": "high.txt", "chunk_index": 0, "section_title": "Claims"},
                "distance": 0.2,
            },
        ]

    def get_chunks_by_ids(self, collection: str, ids: list[str]) -> list[dict]:
        self.get_chunks_collections.append(collection)
        return []


class FakeReranker:
    def rerank(self, query: str, documents: list[str], top_k: int | None = None) -> list[dict]:
        assert query == "What can be claimed?"
        assert documents == ["Low priority context.", "High priority context with claim rules."]
        assert top_k == 5
        return [
            {"index": 1, "document": documents[1], "score": 0.91},
            {"index": 0, "document": documents[0], "score": 0.13},
        ]


class FakeGenerator:
    def __init__(self) -> None:
        self.prompt = ""

    def generate(self, prompt: str) -> dict:
        self.prompt = prompt
        return {
            "answer": "Claims are governed by the claim rules. [1]",
            "tokens": {"prompt": 10, "completion": 8, "total": 18},
            "raw": {"id": "chatcmpl_fake"},
        }


def test_rag_query_service_runs_full_pipeline_with_rerank_generation_and_citation_verification() -> None:
    embedder = FakeEmbedder()
    vector_store = FakeVectorStore()
    generator = FakeGenerator()
    service = RagQueryService(
        embedder=embedder,
        vector_store=vector_store,
        reranker=FakeReranker(),
        generator=generator,
        retrieval_top_k=20,
        rerank_top_k=5,
        embedding_dimension=2,
    )

    result = service.run(prompt="What can be claimed?", collection="guides", agent_id="research-agent", thread_id="t1")

    assert embedder.texts == ["What can be claimed?"]
    assert vector_store.n_results == 20
    assert "[1] high.txt / Claims / chunk 0" in generator.prompt
    assert "High priority context with claim rules." in generator.prompt
    assert result["status"] == "succeeded"
    assert result["finalAnswer"] == "Claims are governed by the claim rules. [1]"
    assert result["tokens"] == {"prompt": 10, "completion": 8, "total": 18}
    assert [match["id"] for match in result["vectorMatches"]] == ["doc_2:0", "doc_1:0"]
    assert result["vectorMatches"][0]["score"] == 0.91
    assert [node["id"] for node in result["nodes"]] == [
        "receive_input",
        "analyze_intent",
        "retrieve_context",
        "rerank_context",
        "expand_parent_context",
        "pack_context",
        "generate_answer",
        "verify_citations",
        "final_answer",
    ]
    verify_event = next(event for event in result["events"] if event["nodeId"] == "verify_citations")
    assert verify_event["payload"]["validCitationIds"] == [1]
    assert vector_store.get_chunks_collections == ["guides", "guides"]


def test_rag_query_service_cache_hit_does_not_mutate_cached_response() -> None:
    embedder = FakeEmbedder()
    service = RagQueryService(
        embedder=embedder,
        vector_store=FakeVectorStore(),
        reranker=FakeReranker(),
        generator=FakeGenerator(),
        embedding_dimension=2,
    )

    first = service.run(prompt="What can be claimed?", collection="guides", agent_id="research-agent", thread_id="t1")
    second = service.run(prompt="What can be claimed?", collection="guides", agent_id="research-agent", thread_id="t1")

    assert first["id"] != second["id"]
    assert first["id"] == first["events"][0]["id"].split("_evt_")[0]
    assert embedder.texts == ["What can be claimed?"]


def test_rag_query_service_returns_insufficient_context_answer_without_generation() -> None:
    class EmptyVectorStore:
        def query_chunks(self, collection: str, embedding: list[float], n_results: int = 5) -> list[dict]:
            return []

    class FailingGenerator:
        def generate(self, prompt: str) -> dict:
            raise AssertionError("generate should not be called without context")

    service = RagQueryService(
        embedder=FakeEmbedder(),
        vector_store=EmptyVectorStore(),
        reranker=FakeReranker(),
        generator=FailingGenerator(),
        embedding_dimension=2,
    )

    result = service.run(prompt="Unknown?", collection="guides", agent_id="research-agent", thread_id=None)

    assert result["status"] == "succeeded"
    assert result["finalAnswer"] == "知识库中没有足够依据回答这个问题。"
    assert result["vectorMatches"] == []


def test_rag_query_service_expands_reranked_chunk_with_neighbor_parent_context() -> None:
    class ClauseVectorStore:
        def query_chunks(self, collection: str, embedding: list[float], n_results: int = 5) -> list[dict]:
            return [
                {
                    "id": "doc_clause:38",
                    "document": "11.1 cancer heavy definition exclusions (1) (2) (3) (4)",
                    "metadata": {
                        "document_id": "doc_clause",
                        "source_file": "policy.pdf",
                        "chunk_index": 38,
                    },
                    "distance": 0.1,
                }
            ]

        def get_chunks_by_ids(self, collection: str, ids: list[str]) -> list[dict]:
            assert collection == "default"
            assert "doc_clause:39" in ids
            return [
                {
                    "id": "doc_clause:39",
                    "document": "continued exclusions (5) leukemia (6) Hodgkin disease (7) neuroendocrine tumor",
                    "metadata": {
                        "document_id": "doc_clause",
                        "source_file": "policy.pdf",
                        "chunk_index": 39,
                    },
                }
            ]

    class ClauseReranker:
        def rerank(self, query: str, documents: list[str], top_k: int | None = None) -> list[dict]:
            return [{"index": 0, "document": documents[0], "score": 1.0}]

    generator = FakeGenerator()
    service = RagQueryService(
        embedder=FakeEmbedder(),
        vector_store=ClauseVectorStore(),
        reranker=ClauseReranker(),
        generator=generator,
        embedding_dimension=2,
    )

    result = service.run(prompt="Define cancer heavy", collection="default", agent_id="research-agent", thread_id=None)

    assert "continued exclusions (5) leukemia (6) Hodgkin disease (7) neuroendocrine tumor" in generator.prompt
    assert result["vectorMatches"][0]["metadata"]["parent_strategy"] == "neighbor_window"
    assert result["vectorMatches"][0]["metadata"]["expanded_from_ids"] == ["doc_clause:38", "doc_clause:39"]
