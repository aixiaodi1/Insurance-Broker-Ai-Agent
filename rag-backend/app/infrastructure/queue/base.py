from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IngestionQueueItem:
    document_id: str
    collection: str
    app_job_id: str | None = None


class QueueClient(Protocol):
    def enqueue_ingestion(self, document_id: str, collection: str, app_job_id: str | None = None) -> str: ...

    def enqueue_ingestions(self, items: list[IngestionQueueItem]) -> list[str]: ...
