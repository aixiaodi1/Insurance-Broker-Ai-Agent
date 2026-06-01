from dataclasses import dataclass, field
from enum import StrEnum


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStage(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    WRITING = "writing"
    DONE = "done"


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    filename: str
    collection: str
    status: DocumentStatus
    mime_type: str
    file_size: int
    source_path: str
    text_path: str | None
    content_hash: str
    chunk_count: int
    error: str | None
    created_at: str
    indexed_at: str | None


@dataclass(frozen=True)
class JobRecord:
    id: str
    rq_job_id: str | None
    document_id: str
    collection: str
    status: JobStatus
    stage: JobStage
    progress: int
    error: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    text: str
    token_count: int
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)
