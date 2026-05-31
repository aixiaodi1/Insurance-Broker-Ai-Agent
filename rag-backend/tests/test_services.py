import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.domain import DocumentRecord, DocumentStatus, JobRecord, JobStage, JobStatus, TextChunk
from app.errors import NonRetryableIngestionError, RetryableIngestionError, ValidationError
from app.infrastructure.queue.base import IngestionQueueItem
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

    def replace_chunks(self, document_id: str, collection: str, chunks: list[dict]) -> None:
        self.chunks = [chunk for chunk in self.chunks if chunk["document_id"] != document_id]
        self.chunks.extend({**chunk, "document_id": document_id, "collection": collection} for chunk in chunks)

    def add_chunks(self, document_id: str, collection: str, chunks: list[dict]) -> None:
        self.chunks.extend({**chunk, "document_id": document_id, "collection": collection} for chunk in chunks)


class FailOnceReplaceRepository(FakeRepository):
    def __init__(self) -> None:
        super().__init__()
        self.replace_attempts = 0

    def replace_chunks(self, document_id: str, collection: str, chunks: list[dict]) -> None:
        self.replace_attempts += 1
        if self.replace_attempts == 1:
            raise RuntimeError("sqlite temporarily locked")
        super().replace_chunks(document_id, collection, chunks)


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str = "text/plain") -> None:
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            content, self._content = self._content, b""
            return content
        content = self._content[:size]
        self._content = self._content[size:]
        return content


class OversizedStreamingUploadFile:
    def __init__(self) -> None:
        self.filename = "huge.txt"
        self.content_type = "text/plain"
        self.read_sizes: list[int] = []
        self._remaining_reads = 2

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            raise AssertionError("upload should be read with bounded chunk sizes")
        self.read_sizes.append(size)
        if self._remaining_reads <= 0:
            return b""
        self._remaining_reads -= 1
        return b"x"


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []
        self.app_job_ids: list[str | None] = []
        self.batch_calls: list[list[IngestionQueueItem]] = []

    def enqueue_ingestion(self, document_id: str, collection: str, app_job_id: str | None = None) -> str:
        return self.enqueue_ingestions(
            [IngestionQueueItem(document_id=document_id, collection=collection, app_job_id=app_job_id)]
        )[0]

    def enqueue_ingestions(self, items: list[IngestionQueueItem]) -> list[str]:
        self.batch_calls.append(items)
        rq_job_ids = []
        for item in items:
            self.enqueued.append((item.document_id, item.collection))
            self.app_job_ids.append(item.app_job_id)
            rq_job_ids.append(item.app_job_id or f"rq-{len(self.enqueued)}")
        return rq_job_ids


class FailingQueue:
    def enqueue_ingestion(self, document_id: str, collection: str, app_job_id: str | None = None) -> str:
        raise RuntimeError("queue unavailable")

    def enqueue_ingestions(self, items: list[IngestionQueueItem]) -> list[str]:
        raise RuntimeError("queue unavailable")


class SecretFailingQueue:
    def enqueue_ingestion(self, document_id: str, collection: str, app_job_id: str | None = None) -> str:
        raise RuntimeError("queue failed at C:/redis/private.rdb Authorization: Bearer sk-secret-token")

    def enqueue_ingestions(self, items: list[IngestionQueueItem]) -> list[str]:
        raise RuntimeError("queue failed at C:/redis/private.rdb Authorization: Bearer sk-secret-token")


class FailingBatchQueue(FakeQueue):
    def enqueue_ingestions(self, items: list[IngestionQueueItem]) -> list[str]:
        self.batch_calls.append(items)
        raise RuntimeError("queue unavailable for batch")


class RepositoryAwareQueue:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository
        self.observed_attached_before_enqueue = False

    def enqueue_ingestion(self, document_id: str, collection: str, app_job_id: str | None = None) -> str:
        return self.enqueue_ingestions(
            [IngestionQueueItem(document_id=document_id, collection=collection, app_job_id=app_job_id)]
        )[0]

    def enqueue_ingestions(self, items: list[IngestionQueueItem]) -> list[str]:
        self.observed_attached_before_enqueue = all(
            item.app_job_id is not None and self.repository.get_job(item.app_job_id).rq_job_id == item.app_job_id
            for item in items
        )
        return [item.app_job_id for item in items if item.app_job_id is not None]


class BatchOrderCapturingQueue(FakeQueue):
    def __init__(self, repository: FakeRepository) -> None:
        super().__init__()
        self.repository = repository
        self.document_count_at_enqueue = 0
        self.job_count_at_enqueue = 0

    def enqueue_ingestion(self, document_id: str, collection: str, app_job_id: str | None = None) -> str:
        raise AssertionError("DocumentService should use batch enqueue")

    def enqueue_ingestions(self, items: list[IngestionQueueItem]) -> list[str]:
        self.document_count_at_enqueue = len(self.repository.documents)
        self.job_count_at_enqueue = len(self.repository.jobs)
        return super().enqueue_ingestions(items)


class AttachFailingRepository(FakeRepository):
    def set_job_rq_id(self, job_id: str, rq_job_id: str) -> None:
        raise RuntimeError("attach failed")


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


class ValueErrorParser:
    def parse(self, path: Path) -> str:
        raise ValueError("bad pdf secret path C:/secrets/private.pdf")


class NonRetryableParser:
    def parse(self, path: Path) -> str:
        raise NonRetryableIngestionError("Document parsing failed.")


class FakeChunker:
    def split(self, text: str) -> list[TextChunk]:
        return [
            TextChunk(chunk_index=0, text="first chunk", token_count=2),
            TextChunk(chunk_index=1, text="second chunk", token_count=2),
        ]


class ValueErrorChunker:
    def split(self, text: str) -> list[TextChunk]:
        raise ValueError("Cannot chunk empty text")


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.texts: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.texts.append(texts)
        return [[0.1, 0.2], [0.3, 0.4]]


class StageCapturingEmbeddingProvider(FakeEmbeddingProvider):
    def __init__(self, repository: FakeRepository, job_id: str) -> None:
        super().__init__()
        self.repository = repository
        self.job_id = job_id
        self.stage_at_call: JobStage | None = None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.stage_at_call = self.repository.get_job(self.job_id).stage
        return super().embed_texts(texts)


class FakeVectorStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def upsert_chunks(
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

    def delete_chunks(self, collection: str, where: dict) -> None:
        self.calls.append({"method": "delete_chunks", "collection": collection, "where": where})

    def add_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        self.upsert_chunks(collection, ids, texts, embeddings, metadatas)


class StageCapturingVectorStore(FakeVectorStore):
    def __init__(self, repository: FakeRepository, job_id: str) -> None:
        super().__init__()
        self.repository = repository
        self.job_id = job_id
        self.stage_at_call: JobStage | None = None

    def upsert_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        self.stage_at_call = self.repository.get_job(self.job_id).stage
        super().upsert_chunks(collection, ids, texts, embeddings, metadatas)


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
    assert repository.get_job(job.id).rq_job_id == job.id
    assert queue.enqueued == [(document.id, "docs")]
    assert queue.app_job_ids == [job.id]
    assert queue.batch_calls == [[IngestionQueueItem(document.id, "docs", job.id)]]


def test_document_service_attaches_deterministic_rq_id_before_enqueue(tmp_path: Path) -> None:
    repository = FakeRepository()
    queue = RepositoryAwareQueue(repository)
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=queue,
        settings=Settings(upload_dir=tmp_path, allowed_extensions=[".txt"], max_upload_mb=1),
    )

    result = asyncio.run(service.upload_files([FakeUploadFile("Guide.TXT", b"hello rag")], "docs"))

    job = result["jobs"][0]
    assert job.rq_job_id == job.id
    assert queue.observed_attached_before_enqueue is True


def test_document_service_does_not_enqueue_when_deterministic_attach_fails(tmp_path: Path) -> None:
    repository = AttachFailingRepository()
    queue = FakeQueue()
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=queue,
        settings=Settings(upload_dir=tmp_path, allowed_extensions=[".txt"], max_upload_mb=1),
    )

    with pytest.raises(RuntimeError, match="attach failed"):
        asyncio.run(service.upload_files([FakeUploadFile("Guide.TXT", b"hello rag")], "docs"))

    assert queue.enqueued == []


def test_document_service_marks_failed_and_cleans_file_when_queue_fails(tmp_path: Path) -> None:
    repository = FakeRepository()
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=FailingQueue(),
        settings=Settings(upload_dir=tmp_path, allowed_extensions=[".txt"], max_upload_mb=1),
    )

    with pytest.raises(RuntimeError, match="queue unavailable"):
        asyncio.run(service.upload_files([FakeUploadFile("Guide.TXT", b"hello rag")], "docs"))

    document = repository.get_document("doc_1")
    job = repository.get_job("job_1")
    assert document.status == DocumentStatus.FAILED
    assert document.error == "queue unavailable"
    assert job.status == JobStatus.FAILED
    assert job.error == "queue unavailable"
    assert not (tmp_path / document.id / "original.txt").exists()
    assert not (tmp_path / document.id).exists()


def test_document_service_sanitizes_queue_failure_before_compensation(tmp_path: Path) -> None:
    repository = FakeRepository()
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=SecretFailingQueue(),
        settings=Settings(upload_dir=tmp_path, allowed_extensions=[".txt"], max_upload_mb=1),
    )

    with pytest.raises(RuntimeError, match="queue failed"):
        asyncio.run(service.upload_files([FakeUploadFile("Guide.TXT", b"hello rag")], "docs"))

    document = repository.get_document("doc_1")
    job = repository.get_job("job_1")
    assert document.status == DocumentStatus.FAILED
    assert job.status == JobStatus.FAILED
    assert document.error == job.error
    assert "private.rdb" not in document.error
    assert "sk-secret-token" not in document.error
    assert not (tmp_path / document.id).exists()


def test_document_service_batch_enqueues_only_after_all_documents_and_jobs_are_prepared(tmp_path: Path) -> None:
    repository = FakeRepository()
    queue = BatchOrderCapturingQueue(repository)
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=queue,
        settings=Settings(upload_dir=tmp_path, allowed_extensions=[".txt"], max_upload_mb=1),
    )

    result = asyncio.run(
        service.upload_files(
            [
                FakeUploadFile("first.txt", b"first file"),
                FakeUploadFile("second.txt", b"second file"),
            ],
            "docs",
        )
    )

    assert queue.document_count_at_enqueue == 2
    assert queue.job_count_at_enqueue == 2
    assert queue.enqueued == [("doc_1", "docs"), ("doc_2", "docs")]
    assert queue.app_job_ids == ["job_1", "job_2"]
    assert queue.batch_calls == [
        [
            IngestionQueueItem("doc_1", "docs", "job_1"),
            IngestionQueueItem("doc_2", "docs", "job_2"),
        ]
    ]
    assert [document.id for document in result["documents"]] == ["doc_1", "doc_2"]
    assert [job.id for job in result["jobs"]] == ["job_1", "job_2"]


def test_document_service_compensates_entire_batch_when_batch_enqueue_fails(tmp_path: Path) -> None:
    repository = FakeRepository()
    queue = FailingBatchQueue()
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=queue,
        settings=Settings(upload_dir=tmp_path, allowed_extensions=[".txt"], max_upload_mb=1),
    )

    with pytest.raises(RuntimeError, match="queue unavailable for batch"):
        asyncio.run(
            service.upload_files(
                [
                    FakeUploadFile("first.txt", b"first file"),
                    FakeUploadFile("second.txt", b"second file"),
                ],
                "docs",
            )
        )

    assert queue.enqueued == []
    assert queue.batch_calls == [
        [
            IngestionQueueItem("doc_1", "docs", "job_1"),
            IngestionQueueItem("doc_2", "docs", "job_2"),
        ]
    ]
    assert set(repository.documents) == {"doc_1", "doc_2"}
    assert set(repository.jobs) == {"job_1", "job_2"}
    for document in repository.documents.values():
        assert document.status == DocumentStatus.FAILED
        assert document.error == "queue unavailable for batch"
        assert not (tmp_path / document.id).exists()
    for job in repository.jobs.values():
        assert job.status == JobStatus.FAILED
        assert job.error == "queue unavailable for batch"


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


def test_document_service_rejects_batch_when_total_upload_size_exceeds_limit(tmp_path: Path) -> None:
    repository = FakeRepository()
    queue = FakeQueue()
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=queue,
        settings=Settings(
            upload_dir=tmp_path,
            allowed_extensions=[".txt"],
            max_upload_mb=1,
            max_upload_batch_mb=0,
        ),
    )

    with pytest.raises(ValidationError, match="Uploaded batch exceeds 0 MB"):
        asyncio.run(
            service.upload_files(
                [
                    FakeUploadFile("first.txt", b"x"),
                    FakeUploadFile("second.txt", b"y"),
                ],
                "docs",
            )
        )

    assert repository.documents == {}
    assert repository.jobs == {}
    assert queue.enqueued == []
    assert list(tmp_path.iterdir()) == []


def test_document_service_rejects_oversized_upload_without_unbounded_read(tmp_path: Path) -> None:
    repository = FakeRepository()
    queue = FakeQueue()
    upload = OversizedStreamingUploadFile()
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=queue,
        settings=Settings(upload_dir=tmp_path, allowed_extensions=[".txt"], max_upload_mb=0, max_upload_batch_mb=1),
    )

    with pytest.raises(ValidationError, match="exceeds 0 MB"):
        asyncio.run(service.upload_files([upload], "docs"))

    assert upload.read_sizes
    assert all(size > 0 for size in upload.read_sizes)
    assert repository.documents == {}
    assert repository.jobs == {}
    assert queue.enqueued == []
    assert list(tmp_path.iterdir()) == []


def test_document_service_validates_entire_batch_before_side_effects(tmp_path: Path) -> None:
    repository = FakeRepository()
    queue = FakeQueue()
    service = DocumentService(
        repository=repository,
        job_service=JobService(repository),
        queue_client=queue,
        settings=Settings(upload_dir=tmp_path, allowed_extensions=[".txt"], max_upload_mb=1),
    )

    with pytest.raises(ValidationError, match="Unsupported file extension"):
        asyncio.run(
            service.upload_files(
                [
                    FakeUploadFile("valid.txt", b"first file"),
                    FakeUploadFile("bad.exe", b"second file"),
                ],
                "docs",
            )
        )

    assert repository.documents == {}
    assert repository.jobs == {}
    assert queue.enqueued == []
    assert list(tmp_path.iterdir()) == []


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

    assert vector_store.calls[0] == {"method": "delete_chunks", "collection": "docs", "where": {"document_id": document.id}}
    call = vector_store.calls[1]
    assert call["ids"] == [f"{document.id}:0", f"{document.id}:1"]
    assert "source_path" not in call["metadatas"][0]
    assert call["metadatas"] == [
        {
            "document_id": document.id,
            "filename": "guide.md",
            "source_file": "guide.md",
            "collection": "docs",
            "chunk_index": 0,
            "upload_time": document.created_at,
            "source": "upload",
            "content_hash": "hash123",
        },
        {
            "document_id": document.id,
            "filename": "guide.md",
            "source_file": "guide.md",
            "collection": "docs",
            "chunk_index": 1,
            "upload_time": document.created_at,
            "source": "upload",
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


def test_ingestion_service_retry_after_vector_write_replaces_chunk_metadata(tmp_path: Path) -> None:
    repository = FailOnceReplaceRepository()
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

    with pytest.raises(RuntimeError, match="sqlite temporarily locked"):
        service.ingest_document(job.id, document.id, "docs")

    service.ingest_document(job.id, document.id, "docs")

    assert repository.replace_attempts == 2
    assert vector_store.calls[0] == {"method": "delete_chunks", "collection": "docs", "where": {"document_id": document.id}}
    assert vector_store.calls[2] == {"method": "delete_chunks", "collection": "docs", "where": {"document_id": document.id}}
    assert [call["ids"] for call in vector_store.calls if "ids" in call] == [
        [f"{document.id}:0", f"{document.id}:1"],
        [f"{document.id}:0", f"{document.id}:1"],
    ]
    assert len(repository.chunks) == 2
    assert [chunk["chroma_id"] for chunk in repository.chunks] == [f"{document.id}:0", f"{document.id}:1"]
    assert repository.get_document(document.id).status == DocumentStatus.INDEXED
    assert repository.get_job(job.id).status == JobStatus.SUCCEEDED


def test_ingestion_service_reports_embedding_and_writing_before_slow_calls(tmp_path: Path) -> None:
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
    embeddings = StageCapturingEmbeddingProvider(repository, job.id)
    vector_store = StageCapturingVectorStore(repository, job.id)
    service = IngestionService(
        repository=repository,
        job_service=JobService(repository),
        parser=FakeParser("parsed text"),
        chunker=FakeChunker(),
        embedding_provider=embeddings,
        vector_store=vector_store,
    )

    service.ingest_document(job.id, document.id, "docs")

    assert embeddings.stage_at_call == JobStage.EMBEDDING
    assert vector_store.stage_at_call == JobStage.WRITING


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


def test_ingestion_service_marks_parser_nonretryable_error_failed_without_retry(tmp_path: Path) -> None:
    repository = FakeRepository()
    document = repository.create_document(
        filename="bad.pdf",
        collection="docs",
        mime_type="application/pdf",
        file_size=1,
        source_path=str(tmp_path / "bad.pdf"),
        content_hash="hash123",
    )
    Path(document.source_path).write_bytes(b"not a pdf")
    job = repository.create_job(document.id, "docs")
    service = IngestionService(
        repository=repository,
        job_service=JobService(repository),
        parser=NonRetryableParser(),
        chunker=FakeChunker(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    with pytest.raises(NonRetryableIngestionError, match="Document parsing failed"):
        service.ingest_document(job.id, document.id, "docs")

    stored_job = repository.get_job(job.id)
    stored_document = repository.get_document(document.id)
    assert stored_job.status == JobStatus.FAILED
    assert stored_job.stage == JobStage.PARSING
    assert stored_job.error == "Document parsing failed."
    assert stored_document.status == DocumentStatus.FAILED
    assert stored_document.error == stored_job.error


def test_ingestion_service_does_not_hide_generic_parser_value_error(tmp_path: Path) -> None:
    repository = FakeRepository()
    document = repository.create_document(
        filename="bad.pdf",
        collection="docs",
        mime_type="application/pdf",
        file_size=1,
        source_path=str(tmp_path / "bad.pdf"),
        content_hash="hash123",
    )
    Path(document.source_path).write_bytes(b"not a pdf")
    job = repository.create_job(document.id, "docs")
    service = IngestionService(
        repository=repository,
        job_service=JobService(repository),
        parser=ValueErrorParser(),
        chunker=FakeChunker(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    with pytest.raises(ValueError, match="bad pdf secret path"):
        service.ingest_document(job.id, document.id, "docs")

    stored_job = repository.get_job(job.id)
    stored_document = repository.get_document(document.id)
    assert stored_job.status == JobStatus.RUNNING
    assert stored_job.stage == JobStage.PARSING
    assert stored_job.error is None
    assert stored_document.status == DocumentStatus.INDEXING
    assert stored_document.error is None


def test_ingestion_service_marks_chunker_value_error_failed_without_retry(tmp_path: Path) -> None:
    repository = FakeRepository()
    document = repository.create_document(
        filename="empty.txt",
        collection="docs",
        mime_type="text/plain",
        file_size=1,
        source_path=str(tmp_path / "empty.txt"),
        content_hash="hash123",
    )
    Path(document.source_path).write_text("content", encoding="utf-8")
    job = repository.create_job(document.id, "docs")
    service = IngestionService(
        repository=repository,
        job_service=JobService(repository),
        parser=FakeParser("parsed text"),
        chunker=ValueErrorChunker(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    with pytest.raises(NonRetryableIngestionError, match="Document chunking failed"):
        service.ingest_document(job.id, document.id, "docs")

    stored_job = repository.get_job(job.id)
    stored_document = repository.get_document(document.id)
    assert stored_job.status == JobStatus.FAILED
    assert stored_job.stage == JobStage.CHUNKING
    assert stored_job.progress == 35
    assert stored_job.error == "Document chunking failed: Cannot chunk empty text"
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


def test_ingestion_service_marks_retry_exhausted_failed() -> None:
    repository = FakeRepository()
    document = repository.create_document(
        filename="retry.txt",
        collection="docs",
        mime_type="text/plain",
        file_size=1,
        source_path="/tmp/retry.txt",
        content_hash="hash123",
    )
    job = repository.create_job(document.id, "docs")
    service = IngestionService(
        repository=repository,
        job_service=JobService(repository),
        parser=FakeParser("parsed text"),
        chunker=FakeChunker(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    service.mark_retry_exhausted(job.id, document.id, "retries exhausted")

    stored_job = repository.get_job(job.id)
    stored_document = repository.get_document(document.id)
    assert stored_job.status == JobStatus.FAILED
    assert stored_job.error == "retries exhausted"
    assert stored_document.status == DocumentStatus.FAILED
    assert stored_document.error == "retries exhausted"


def test_ingestion_service_sanitizes_retry_exhausted_error_before_persisting() -> None:
    repository = FakeRepository()
    document = repository.create_document(
        filename="retry.txt",
        collection="docs",
        mime_type="text/plain",
        file_size=1,
        source_path="/tmp/retry.txt",
        content_hash="hash123",
    )
    job = repository.create_job(document.id, "docs")
    service = IngestionService(
        repository=repository,
        job_service=JobService(repository),
        parser=FakeParser("parsed text"),
        chunker=FakeChunker(),
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeVectorStore(),
    )

    service.mark_retry_exhausted(
        job.id,
        document.id,
        "failed at C:/secrets/private.db Authorization: Bearer sk-secret-token token=abc123",
    )

    stored_job = repository.get_job(job.id)
    stored_document = repository.get_document(document.id)
    assert stored_job.status == JobStatus.FAILED
    assert stored_document.status == DocumentStatus.FAILED
    assert stored_job.error == stored_document.error
    assert "private.db" not in stored_job.error
    assert "sk-secret-token" not in stored_job.error
    assert "abc123" not in stored_job.error
