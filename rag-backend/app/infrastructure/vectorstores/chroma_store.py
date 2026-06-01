from math import isfinite
from pathlib import Path

import chromadb

from app.errors import NonRetryableIngestionError, RetryableIngestionError
from app.sanitization import sanitize_error_message


class ChromaVectorStore:
    def __init__(self, persist_dir: Path) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return

        close = getattr(self.client, "close", None)
        if callable(close):
            close()
        else:
            system = getattr(self.client, "_system", None)
            stop = getattr(system, "stop", None)
            if callable(stop):
                stop()

        self._closed = True

    def ensure_collection(self, name: str) -> None:
        self.client.get_or_create_collection(name)

    def list_collections(self) -> list[str]:
        collections = self.client.list_collections()
        names = [collection if isinstance(collection, str) else collection.name for collection in collections]
        return sorted(names)

    def upsert_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        if len({len(ids), len(texts), len(embeddings), len(metadatas)}) != 1:
            raise NonRetryableIngestionError("Chroma chunk ids, texts, embeddings, and metadatas must have the same length.")

        if not ids:
            raise NonRetryableIngestionError("Chroma chunk upsert requires at least one chunk.")

        if len(ids) != len(set(ids)):
            raise NonRetryableIngestionError("Chroma chunk ids must not contain duplicate values.")

        if any(not isinstance(metadata, dict) for metadata in metadatas):
            raise NonRetryableIngestionError("Chroma chunk metadata entries must be dictionaries.")

        if any(not isinstance(embedding, list) for embedding in embeddings):
            raise NonRetryableIngestionError("Chroma chunk embedding entries must be lists.")

        dimension = len(embeddings[0])
        if dimension == 0:
            raise NonRetryableIngestionError("Chroma chunk embedding entries must be non-empty lists.")

        if any(len(embedding) != dimension for embedding in embeddings):
            raise NonRetryableIngestionError("Chroma chunk embeddings must have the same dimensions.")

        if any(
            isinstance(value, bool) or not isinstance(value, int | float) or not isfinite(float(value))
            for embedding in embeddings
            for value in embedding
        ):
            raise NonRetryableIngestionError("Chroma chunk embedding values must be finite numeric values.")

        try:
            target = self.client.get_or_create_collection(collection)
            target.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
        except Exception as exc:
            raise RetryableIngestionError(f"Chroma write failed: {sanitize_error_message(str(exc))}") from exc

    def query_chunks(self, collection: str, embedding: list[float], n_results: int = 5) -> list[dict]:
        try:
            target = self.client.get_or_create_collection(collection)
            result = target.query(
                query_embeddings=[embedding],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise RetryableIngestionError(f"Chroma query failed: {sanitize_error_message(str(exc))}") from exc

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return [
            {
                "id": chunk_id,
                "document": document,
                "metadata": metadata or {},
                "distance": distance,
            }
            for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances, strict=False)
        ]

    def get_chunks_by_ids(self, collection: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []

        try:
            target = self.client.get_or_create_collection(collection)
            result = target.get(ids=ids, include=["documents", "metadatas"])
        except Exception as exc:
            raise RetryableIngestionError(f"Chroma get failed: {sanitize_error_message(str(exc))}") from exc

        result_ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        by_id = {
            chunk_id: {
                "id": chunk_id,
                "document": document,
                "metadata": metadata or {},
            }
            for chunk_id, document, metadata in zip(result_ids, documents, metadatas, strict=False)
        }
        return [by_id[chunk_id] for chunk_id in ids if chunk_id in by_id]

    def delete_chunks(self, collection: str, where: dict) -> None:
        try:
            target = self.client.get_or_create_collection(collection)
            target.delete(where=where)
        except Exception as exc:
            raise RetryableIngestionError(
                f"Chroma delete failed: {sanitize_error_message(str(exc))}"
            ) from exc

    def delete_collection(self, name: str) -> None:
        try:
            self.client.delete_collection(name)
        except Exception as exc:
            raise RetryableIngestionError(
                f"Chroma delete_collection failed: {sanitize_error_message(str(exc))}"
            ) from exc

    def add_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        self.upsert_chunks(collection, ids, texts, embeddings, metadatas)
