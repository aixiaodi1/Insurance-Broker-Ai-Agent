from typing import Protocol


class VectorStore(Protocol):
    def ensure_collection(self, name: str) -> None: ...
    def list_collections(self) -> list[str]: ...
    def upsert_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None: ...
    def close(self) -> None: ...
