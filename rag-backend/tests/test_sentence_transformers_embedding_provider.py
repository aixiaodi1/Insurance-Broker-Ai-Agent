import pytest

from app.errors import NonRetryableIngestionError
from app.infrastructure.embeddings.sentence_transformers import SentenceTransformersEmbeddingProvider


class FakeLangChainEmbeddings:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.documents: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.append(texts)
        return [[float(index), 0.5] for index, _text in enumerate(texts)]


class FakeSentenceTransformerModel:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.encoded: list[list[str]] = []

    def encode(self, texts: list[str], convert_to_numpy: bool = False) -> list[list[float]]:
        self.encoded.append(texts)
        return [[float(index), 0.25] for index, _text in enumerate(texts)]


class BadLangChainEmbeddings:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, "bad"] for _text in texts]


class ArrayLikeVector:
    def tolist(self) -> list[float]:
        return [0.75, 0.25]


class ArrayLikeSentenceTransformerModel:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def encode(self, texts: list[str], convert_to_numpy: bool = False, normalize_embeddings: bool = True) -> list[ArrayLikeVector]:
        return [ArrayLikeVector() for _text in texts]


def test_sentence_transformers_provider_embeds_direct_sentence_transformer_in_batches() -> None:
    provider = SentenceTransformersEmbeddingProvider(
        model_name="shibing624/text2vec-base-chinese",
        batch_size=2,
        model_cls=FakeSentenceTransformerModel,
    )

    assert provider.embed_texts(["one", "two", "three"]) == [[0.0, 0.25], [1.0, 0.25], [0.0, 0.25]]
    assert provider._model.model_name == "shibing624/text2vec-base-chinese"
    assert provider._model.encoded == [["one", "two"], ["three"]]


def test_sentence_transformers_provider_supports_langchain_compatible_classes() -> None:
    provider = SentenceTransformersEmbeddingProvider(
        model_name="shibing624/text2vec-base-chinese",
        batch_size=2,
        model_cls=FakeLangChainEmbeddings,
    )

    assert provider.embed_texts(["one", "two", "three"]) == [[0.0, 0.5], [1.0, 0.5], [0.0, 0.5]]
    assert provider._model.documents == [["one", "two"], ["three"]]


def test_sentence_transformers_provider_accepts_array_like_vectors() -> None:
    provider = SentenceTransformersEmbeddingProvider(
        model_name="local-model",
        batch_size=2,
        model_cls=ArrayLikeSentenceTransformerModel,
    )

    assert provider.embed_texts(["hello", "world"]) == [[0.75, 0.25], [0.75, 0.25]]


def test_sentence_transformers_provider_rejects_invalid_vectors() -> None:
    provider = SentenceTransformersEmbeddingProvider(
        model_name="local-model",
        batch_size=2,
        model_cls=BadLangChainEmbeddings,
    )

    with pytest.raises(NonRetryableIngestionError, match="finite numeric"):
        provider.embed_texts(["hello"])
