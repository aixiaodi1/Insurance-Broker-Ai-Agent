from typing import Protocol


class QueueClient(Protocol):
    def enqueue_ingestion(self, document_id: str, collection: str) -> str: ...
