import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.domain import DocumentRecord, DocumentStatus, JobRecord, JobStage, JobStatus, TextChunk
from app.errors import NonRetryableIngestionError, RetryableIngestionError, ValidationError
from app.services.document_service import DocumentService
from app.services.ingestion_service import IngestionService
from app.services.job_service import JobService


class FakeRepository:
    def __init__(self) -> None:
        self.documents: dict[str, DocumentRecord] = {}
        self.jobs: dict[str, JobRecord] = {}
        self.chunks: list[dict] = []
        self.source_path_updates: list[tuple[str, str]] = []
        self.document_counter = 0
        self.job_counter = 0

    def create_document(
        self,
        filename: str,
        collection: str,
        mime_type: str,
        file_size: int,
        source_path: str,
        content_hash: str,
    ) -> DocumentRecord:
        self.document_counter += 1
        document = DocumentRecord(
            id=f"doc_{self.document_counter}",
            filename=filename,
            collection=collection,
            status=DocumentStatus.UPLOADED,
            mime_type=mime_type,
            file_size=file_size,
            source_path=source_path,
            text_path=None,
            content_hash=content_hash,
            chunk_count=0,
            error=None,
            created_at=f"2026-05-24T00:00:0{self.document_counter}+08:00",
            indexed_at=None,
        )
        self.documents[document.id] = document
        return document

    def get_document(self, document_id: str) -> DocumentRecord:
        return self.documents[document_id]

    def mark_document_indexing(self, document_id: str) -> None:
        self.documents[document_id] = replace(
            self.documents[document_id],
            status=DocumentStatus.INDEXING,
            error=None,
        )

    def mark_document_indexed(self, document_id: str, chunk_count: int) -> None:
        self.documents[document_id] = replace(
            self.documents[document_id],
            status=DocumentStatus.INDEXED,
            chunk_count=chunk_count,
            error=None,
            indexed_at="2026-05-24T00:10:00+08:00",
        )

    def mark_document_failed(self, document_id: str, error: str) -> None:
        self.documents[document_id] = replace(
            self.documents[document_id],
            status=DocumentStatus.FAILED,
            error=error,
        )

    def set_document_text_path(self, document_id: str, text_path: str) -> None:
        self.documents[document_id] = replace(self.documents[document_id], text_path=text_path)

    def update_document_source_path(self, document_id: str, source_path: str) -> DocumentRecord:
        self.source_path_updates.append((document_id, source_path))
        self.documents[document_id] = replace(self.documents[document_id], source_path=source_path)
        return self.documents[document_id]

    def create_job(self, document_id: str, collection: str) -> JobRecord:
        self.job_counter += 1
        job = JobRecord(
            id=f"job_{self.job_counter}",
            rq_job_id=None,
            document_id=document_id,
            collection=collection,
            status=JobStatus.QUEUED,
            stage=JobStage.UPLOADED,
            progress=5,
            error=None,
            created_at=f"2026-05-24T00:01:0{self.job_counter}+08:00",
            updated_at=f"2026-05-24T00:01:0{self.job_counter}+08:00",
            started_at=None,
            finished_at=None,
        )
        self.jobs[job.id] = job
        return job

    def set_job_rq_id(self, job_id: str, rq_job_id: str) -> None:
        self.jobs[job_id] = replace(self.jobs[job_id], rq_job_id=rq_job_id)

    def get_job(self, job_id: str) -> JobRecord:
        return self.jobs[job_id]

    def get_job_by_rq_id(self, rq_job_id: str) -> JobRecord:
        return next(job for job in self.jobs.values() if job.rq_job_id == rq_job_id)

    def update_job(
        self,
        job_id: str,
        status: JobStatus,
        stage: JobStage,
        progress: int,
        error: str | None = None,
    ) -> None:
        self.jobs[job_id] = replace(
            self.jobs[job_id],
            status=status,
            stage=stage,
            progress=progress,
            error=error,
        )

    def add_chunks(self, document_id: str, collection: str, chunks: list[dict]) -> None:
        self.chunks.extend({**chunk, "document_id": document_id, "collection": collection} for chunk in chunks)


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str = "text/plain") -> None:
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []

    def enqueue_ingestion(self, document_id: str, collection: str) -> str:
        self.enqueued.append((document_id, collection))
        return f"rq-{len(self.enqueued)}"


class FakeParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.paths: list[Path] = []

    def parse(self, path: Path) -> str:
        self.paths.append(path)
        return self.text


class RetryableParser:
    def parse(self, path: Path) -> str:
        raise RetryableIngestionError("parser temporarily unavailable")


class FakeChunker:
    def split(self, text: str) -> list[TextChunk]:
        return [
            TextChunk(chunk_index=0, text="first chunk", token_count=2),
            TextChunk(chunk_index=1, text="second chunk", token_count=2),
        ]


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.texts: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.texts.append(texts)
        return [[0.1, 0.2], [0.3, 0.4]]


class FakeVectorStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def add_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        self.calls.append(
            {
                "collection": collection,
                "ids": ids,
                "texts": texts,
                "embeddings": embeddings,
                "metadatas": metadatas,
            }
        )


def test_document_service_upload_files_saves_creates_jobs_and_enqueues(tmp_path: Path) -> None:
    repository = FakeRepository()
    queue = FakeQueue()
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=queue,
        settings=Settings(upload_dir=tmp_path, allowed_extensions=[".txt"], max_upload_mb=1),
    )

    result = asyncio.run(service.upload_files([FakeUploadFile("Guide.TXT", b"hello rag")], " docs "))

    document = result["documents"][0]
    job = result["jobs"][0]
    saved_path = tmp_path / document.id / "original.txt"

    assert saved_path.read_bytes() == b"hello rag"
    assert document.collection == "docs"
    assert document.filename == "Guide.TXT"
    assert document.file_size == 9
    assert document.source_path == str(saved_path)
    assert repository.source_path_updates == [(document.id, str(saved_path))]
    assert repository.get_document(document.id).source_path == str(saved_path)
    assert document.content_hash == "d5998278b9de71718106464bf36ffd0b37e4eb7e2592b0cfd3081e316ac78313"
    assert job.document_id == document.id
    assert repository.get_job(job.id).rq_job_id == "rq-1"
    assert queue.enqueued == [(document.id, "docs")]


@pytest.mark.parametrize(
    ("files", "collection", "settings", "message"),
    [
        ([FakeUploadFile("guide.txt", b"hello")], "   ", {}, "Collection is required"),
        ([FakeUploadFile("guide.exe", b"hello")], "docs", {}, "Unsupported file extension"),
        ([FakeUploadFile("guide.txt", b"x" * 2)], "docs", {"max_upload_mb": 0}, "exceeds 0 MB"),
    ],
)
def test_document_service_upload_validation_failures(
    tmp_path: Path,
    files: list[FakeUploadFile],
    collection: str,
    settings: dict,
    message: str,
) -> None:
    repository = FakeRepository()
    queue = FakeQueue()
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=queue,
        settings=Settings(
            upload_dir=tmp_path,
            allowed_extensions=[".txt"],
            max_upload_mb=settings.get("max_upload_mb", 1),
        ),
    )

    with pytest.raises(ValidationError, match=message):
        asyncio.run(service.upload_files(files, collection))

    assert repository.documents == {}
    assert repository.jobs == {}
    assert queue.enqueued == []


def test_job_service_reads_and_attaches_jobs_by_public_repository_methods() -> None:
    repository = FakeRepository()
    document = repository.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=42,
        source_path="/tmp/guide.md",
        content_hash="hash123",
    )
    job_service = JobService(repository)
    job = job_service.create_job(document.id, "docs")

    attached = job_service.attach_rq_job(job.id, "rq-job-123")

    assert attached.rq_job_id == "rq-job-123"
    assert job_service.get_job(job.id).id == job.id
    assert job_service.get_job_by_rq_id("rq-job-123").id == job.id


def test_ingestion_service_ingests_document_through_all_stages(tmp_path: Path) -> None:
    repository = FakeRepository()
    document = repository.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=42,
        source_path=str(tmp_path / "guide.md"),
        content_hash="hash123",
    )
    Path(document.source_path).write_text("# Guide", encoding="utf-8")
    job = repository.create_job(document.id, "docs")
    vector_store = FakeVectorStore()
    embeddings = FakeEmbeddingProvider()
    service = IngestionService(
        repository=repository,
        job_service=JobService(repository),
        parser=FakeParser("parsed text"),
        chunker=FakeChunker(),
        embedding_provider=embeddings,
        vector_store=vector_store,
    )

    service.ingest_document(job.id, document.id, "docs")

    assert repository.get_job(job.id).status == JobStatus.SUCCEEDED
    assert repository.get_job(job.id).stage == JobStage.DONE
    assert repository.get_job(job.id).progress == 100
    assert repository.get_document(document.id).status == DocumentStatus.INDEXED
    assert repository.get_document(document.id).chunk_count == 2
    assert Path(repository.get_document(document.id).text_path).read_text(encoding="utf-8") == "parsed text"
    assert embeddings.texts == [["first chunk", "second chunk"]]


def test_ingestion_service_writes_chroma_ids_and_metadata(tmp_path: Path) -> None:
    repository = FakeRepository()
    document = repository.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=42,
        source_path=str(tmp_path / "guide.md"),
        content_hash="hash123",
    )
    Path(document.source_path).write_text("# Guide", encoding="utf-8")
    job = repository.create_job(document.id, "docs")
    vector_store = FakeVectorStore()
    service = IngestionService(
        repository=repository,
        job_service=JobService(repository),
        parser=FakeParser("parsed text"),
        chunker=FakeChunker(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=vector_store,
    )

    service.ingest_document(job.id, document.id, "docs")

    call = vector_store.calls[0]
    assert call["ids"] == [f"{document.id}:0", f"{document.id}:1"]
    assert call["metadatas"] == [
        {
            "document_id": document.id,
            "filename": "guide.md",
            "source_file": "guide.md",
            "collection": "docs",
            "chunk_index": 0,
            "upload_time": document.created_at,
            "source": str(tmp_path / "guide.md"),
            "content_hash": "hash123",
        },
        {
            "document_id": document.id,
            "filename": "guide.md",
            "source_file": "guide.md",
            "collection": "docs",
            "chunk_index": 1,
            "upload_time": document.created_at,
            "source": str(tmp_path / "guide.md"),
            "content_hash": "hash123",
        },
    ]
    assert repository.chunks == [
        {
            "document_id": document.id,
            "collection": "docs",
            "chunk_index": 0,
            "chroma_id": f"{document.id}:0",
            "content_preview": "first chunk",
            "token_count": 2,
            "source_file": "guide.md",
            "upload_time": document.created_at,
        },
        {
            "document_id": document.id,
            "collection": "docs",
            "chunk_index": 1,
            "chroma_id": f"{document.id}:1",
            "content_preview": "second chunk",
            "token_count": 2,
            "source_file": "guide.md",
            "upload_time": document.created_at,
        },
    ]


def test_ingestion_service_marks_empty_parsed_text_failed_without_retry(tmp_path: Path) -> None:
    repository = FakeRepository()
    document = repository.create_document(
        filename="empty.txt",
        collection="docs",
        mime_type="text/plain",
        file_size=1,
        source_path=str(tmp_path / "empty.txt"),
        content_hash="hash123",
    )
    Path(document.source_path).write_text("", encoding="utf-8")
    job = repository.create_job(document.id, "docs")
    service = IngestionService(
        repository=repository,
        job_service=JobService(repository),
        parser=FakeParser(" \n\t "),
        chunker=FakeChunker(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    with pytest.raises(NonRetryableIngestionError, match="empty"):
        service.ingest_document(job.id, document.id, "docs")

    stored_job = repository.get_job(job.id)
    stored_document = repository.get_document(document.id)
    assert stored_job.status == JobStatus.FAILED
    assert stored_job.stage == JobStage.PARSING
    assert stored_job.progress == 20
    assert stored_document.status == DocumentStatus.FAILED
    assert stored_document.error == stored_job.error


def test_ingestion_service_persists_retryable_error_and_preserves_progress(tmp_path: Path) -> None:
    repository = FakeRepository()
    document = repository.create_document(
        filename="retry.txt",
        collection="docs",
        mime_type="text/plain",
        file_size=1,
        source_path=str(tmp_path / "retry.txt"),
        content_hash="hash123",
    )
    Path(document.source_path).write_text("retry", encoding="utf-8")
    job = repository.create_job(document.id, "docs")
    service = IngestionService(
        repository=repository,
        job_service=JobService(repository),
        parser=RetryableParser(),
        chunker=FakeChunker(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    with pytest.raises(RetryableIngestionError, match="temporarily unavailable"):
        service.ingest_document(job.id, document.id, "docs")

    stored_job = repository.get_job(job.id)
    stored_document = repository.get_document(document.id)
    assert stored_job.status == JobStatus.RUNNING
    assert stored_job.stage == JobStage.PARSING
    assert stored_job.progress == 20
    assert stored_job.error == "parser temporarily unavailable"
    assert stored_document.status == DocumentStatus.INDEXING
