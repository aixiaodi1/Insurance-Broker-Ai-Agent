from collections.abc import Callable
from math import isfinite
from typing import Any

from app.errors import NonRetryableIngestionError


class SentenceTransformersEmbeddingProvider:
    def __init__(
        self,
        model_name: str,
        batch_size: int,
        model_cls: Callable[..., Any] | None = None,
    ) -> None:
        if batch_size <= 0:
            raise NonRetryableIngestionError("Embedding batch size must be greater than zero.")

        self._model_name = model_name
        self._batch_size = batch_size
        self._model_cls = model_cls or _load_sentence_transformer_cls()
        self._model = self._model_cls(model_name)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            embeddings.extend(self._embed_batch(batch))
        return embeddings

    def health_check(self) -> None:
        if self._model is None:
            raise NonRetryableIngestionError("Local embedding model is unavailable.")

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if callable(getattr(self._model, "encode", None)):
            raw_embeddings = self._model.encode(texts, convert_to_numpy=False)
        elif callable(getattr(self._model, "embed_documents", None)):
            raw_embeddings = self._model.embed_documents(texts)
        elif callable(getattr(self._model, "embed_query", None)):
            raw_embeddings = [self._model.embed_query(text) for text in texts]
        else:
            raise NonRetryableIngestionError("Local embedding model does not expose encode, embed_documents, or embed_query.")

        if len(raw_embeddings) != len(texts):
            raise NonRetryableIngestionError("Local embedding model returned an unexpected number of embeddings.")

        return [_validate_vector(vector) for vector in raw_embeddings]


def _validate_vector(vector: object) -> list[float]:
    if not isinstance(vector, list):
        raise NonRetryableIngestionError("Local embedding model returned a non-list embedding.")
    if not vector:
        raise NonRetryableIngestionError("Local embedding model returned an empty embedding.")
    if any(
        isinstance(value, bool) or not isinstance(value, int | float) or not isfinite(float(value))
        for value in vector
    ):
        raise NonRetryableIngestionError("Local embedding model returned a non-finite numeric value.")
    return [float(value) for value in vector]


def _load_sentence_transformer_cls() -> Callable[..., Any]:
    try:
        module = __import__("sentence_transformers", fromlist=["SentenceTransformer"])
        return getattr(module, "SentenceTransformer")
    except (ImportError, AttributeError):
        pass

    candidates = [
        ("langchain_huggingface", "HuggingFaceEmbeddings"),
        ("langchain_community.embeddings", "SentenceTransformerEmbeddings"),
        ("langchain.embeddings", "SentenceTransformerEmbeddings"),
        ("langchain.embeddings", "SentenceTransformersEmbeddings"),
    ]
    for module_name, class_name in candidates:
        try:
            module = __import__(module_name, fromlist=[class_name])
            return getattr(module, class_name)
        except (ImportError, AttributeError):
            continue

    raise NonRetryableIngestionError(
        "SentenceTransformers embeddings are not installed. "
        "Install sentence-transformers, point RAG_PYTHON at your RAG environment, or set EMBEDDING_PROVIDER=api."
    )
