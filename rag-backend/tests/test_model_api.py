from fastapi.testclient import TestClient

from app.model_api import _resolve_model_max_length, create_model_api_app


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bool]] = []

    def encode(self, texts: list[str], normalize_embeddings: bool = True) -> list[list[float]]:
        self.calls.append((texts, normalize_embeddings))
        return [[float(index), 0.5] for index, _text in enumerate(texts)]


class FakeCrossEncoder:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [0.1 if document == "low" else 0.9 for _query, document in pairs]


def test_embeddings_endpoint_accepts_single_input_and_returns_openai_shape() -> None:
    embedding_model = FakeEmbeddingModel()
    client = TestClient(
        create_model_api_app(
            embedding_model_factory=lambda: embedding_model,
            rerank_model_factory=FakeCrossEncoder,
        )
    )

    response = client.post("/v1/embeddings", json={"model": "local", "input": "hello"})

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "model": "local",
        "embeddings": [[0.0, 0.5]],
        "data": [{"object": "embedding", "index": 0, "embedding": [0.0, 0.5]}],
    }
    assert embedding_model.calls == [(["hello"], True)]


def test_embeddings_endpoint_preserves_batch_order() -> None:
    client = TestClient(
        create_model_api_app(
            embedding_model_factory=FakeEmbeddingModel,
            rerank_model_factory=FakeCrossEncoder,
        )
    )

    response = client.post("/v1/embeddings", json={"input": ["first", "second"]})

    assert response.status_code == 200
    assert response.json()["embeddings"] == [[0.0, 0.5], [1.0, 0.5]]


def test_rerank_endpoint_sorts_documents_by_score() -> None:
    client = TestClient(
        create_model_api_app(
            embedding_model_factory=FakeEmbeddingModel,
            rerank_model_factory=FakeCrossEncoder,
        )
    )

    response = client.post(
        "/v1/rerank",
        json={
            "model": "reranker",
            "query": "question",
            "documents": ["low", "high"],
            "top_k": 1,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "model": "reranker",
        "results": [{"index": 1, "document": "high", "score": 0.9}],
    }


def test_embedding_model_max_length_uses_model_limit_when_tokenizer_is_larger() -> None:
    class Tokenizer:
        model_max_length = 2797

    class Config:
        max_position_embeddings = 512

    class Model:
        config = Config()

    assert _resolve_model_max_length(Tokenizer(), Model()) == 512


def test_embedding_model_max_length_ignores_transformers_sentinel_values() -> None:
    class Tokenizer:
        model_max_length = 1000000000000000019884624838656

    class Config:
        max_position_embeddings = 512

    class Model:
        config = Config()

    assert _resolve_model_max_length(Tokenizer(), Model()) == 512
