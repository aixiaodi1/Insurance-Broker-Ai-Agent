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
        model: object | None = None,
    ) -> None:
        if batch_size <= 0:
            raise NonRetryableIngestionError("Embedding batch size must be greater than zero.")

        self._model_name = model_name
        self._batch_size = batch_size
        if model is not None:
            self._model = model
        else:
            self._model_cls = model_cls or _load_sentence_transformer_cls()
            try:
                self._model = self._model_cls(model_name, local_files_only=True)
            except TypeError:
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
            try:
                raw_embeddings = self._model.encode(texts, convert_to_numpy=False, normalize_embeddings=True)
            except TypeError:
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
    if callable(getattr(vector, "tolist", None)):
        vector = vector.tolist()

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
    candidates = [
        ("langchain_huggingface", "HuggingFaceEmbeddings"),
        ("langchain_community.embeddings", "SentenceTransformerEmbeddings"),
        ("langchain.embeddings", "SentenceTransformerEmbeddings"),
        ("langchain.embeddings", "SentenceTransformersEmbeddings"),
        ("sentence_transformers", "SentenceTransformer"),
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
