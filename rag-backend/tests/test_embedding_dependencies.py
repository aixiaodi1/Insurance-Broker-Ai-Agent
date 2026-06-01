from app.config import Settings
import app.dependencies as dependencies
from app.dependencies import build_embedder
from app.infrastructure.embeddings.local_api import LocalApiEmbeddingProvider


class FakeSentenceTransformersEmbeddingProvider:
    def __init__(self, model_name: str, batch_size: int, model: object | None = None) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.model = model


def test_build_embedder_defaults_to_sentence_transformers(monkeypatch) -> None:
    monkeypatch.setattr(
        dependencies,
        "SentenceTransformersEmbeddingProvider",
        FakeSentenceTransformersEmbeddingProvider,
    )

    embedder = build_embedder(Settings(_env_file=None))

    assert isinstance(embedder, FakeSentenceTransformersEmbeddingProvider)
    assert embedder.model_name == "shibing624/text2vec-base-chinese"


def test_build_embedder_can_still_use_api_provider() -> None:
    embedder = build_embedder(
        Settings(
            embedding_provider="api",
            embedding_api_base_url="http://localhost:9000",
            embedding_model="embo-01",
        )
    )

    assert isinstance(embedder, LocalApiEmbeddingProvider)
