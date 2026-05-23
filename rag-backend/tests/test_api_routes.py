from dataclasses import asdict

from fastapi.testclient import TestClient

from app.dependencies import get_document_service, get_embedder, get_queue_client, get_repository, get_vector_store
from app.domain import DocumentRecord, DocumentStatus, JobRecord, JobStage, JobStatus
from app.errors import ValidationError
from app.main import create_app


NOW = "2026-05-24T08:00:00+08:00"


def make_document(
    document_id: str = "doc_1",
    collection: str = "guides",
    status: DocumentStatus = DocumentStatus.UPLOADED,
) -> DocumentRecord:
    return DocumentRecord(
        id=document_id,
        filename="guide.txt",
        collection=collection,
        status=status,
        mime_type="text/plain",
        file_size=11,
        source_path=f"/uploads/{document_id}/original.txt",
        text_path=None,
        content_hash="abc123",
        chunk_count=2 if status == DocumentStatus.INDEXED else 0,
        error=None,
        created_at=NOW,
        indexed_at=NOW if status == DocumentStatus.INDEXED else None,
    )


def make_job(
    job_id: str = "job_1",
    document_id: str = "doc_1",
    status: JobStatus = JobStatus.RUNNING,
    stage: JobStage = JobStage.EMBEDDING,
    progress: int = 60,
    error: str | None = None,
) -> JobRecord:
    return JobRecord(
        id=job_id,
        rq_job_id="rq_1",
        document_id=document_id,
        collection="guides",
        status=status,
        stage=stage,
        progress=progress,
        error=error,
        created_at=NOW,
        updated_at=NOW,
        started_at=NOW,
        finished_at=None,
    )


class FakeDocumentService:
    def __init__(self) -> None:
        self.uploaded: tuple[list, str] | None = None

    async def upload_files(self, files: list, collection: str) -> dict:
        self.uploaded = (files, collection)
        return {"documents": [make_document()], "jobs": [make_job(status=JobStatus.QUEUED, stage=JobStage.UPLOADED, progress=5)]}


class RejectingDocumentService:
    async def upload_files(self, files: list, collection: str) -> dict:
        raise ValidationError("Unsupported file extension: .xlsx.")


class FakeRepository:
    def __init__(self) -> None:
        self.documents = [
            make_document("doc_1", "guides", DocumentStatus.INDEXED),
            make_document("doc_2", "drafts", DocumentStatus.UPLOADED),
        ]
        self.job = make_job(error="embedding unavailable")
        self.initialized = False

    def initialize(self) -> None:
        self.initialized = True

    def list_documents(self, collection: str | None = None) -> list[DocumentRecord]:
        if collection is None:
            return self.documents
        return [document for document in self.documents if document.collection == collection]

    def get_job(self, job_id: str) -> JobRecord:
        if job_id != self.job.id:
            raise KeyError(job_id)
        return self.job


class FakeQueueClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def ping(self) -> bool:
        if self.fail:
            raise RuntimeError("redis unavailable")
        return True


class FakeVectorStore:
    def list_collections(self) -> list[str]:
        return ["drafts", "guides"]


class FakeEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]


def make_client(overrides: dict | None = None) -> TestClient:
    app = create_app()
    for dependency, replacement in (overrides or {}).items():
        app.dependency_overrides[dependency] = replacement
    return TestClient(app)


def test_upload_txt_returns_documents_and_jobs() -> None:
    service = FakeDocumentService()
    client = make_client({get_document_service: lambda: service})

    response = client.post(
        "/documents/upload",
        data={"collection": "guides"},
        files=[("files", ("guide.txt", b"hello world", "text/plain"))],
    )

    assert response.status_code == 200
    assert response.json() == {
        "documents": [{**asdict(make_document()), "status": "uploaded"}],
        "jobs": [{**asdict(make_job(status=JobStatus.QUEUED, stage=JobStage.UPLOADED, progress=5)), "status": "queued", "stage": "uploaded"}],
    }
    assert service.uploaded is not None
    assert service.uploaded[1] == "guides"


def test_upload_rejects_xlsx_with_400() -> None:
    client = make_client({get_document_service: lambda: RejectingDocumentService()})

    response = client.post(
        "/documents/upload",
        data={"collection": "guides"},
        files=[("files", ("sheet.xlsx", b"workbook", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))],
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported file extension: .xlsx."}


def test_get_job_returns_status_stage_progress_error_and_timestamps() -> None:
    repository = FakeRepository()
    client = make_client({get_repository: lambda: repository})

    response = client.get("/jobs/job_1")

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "job_1",
        "document_id": "doc_1",
        "status": "running",
        "stage": "embedding",
        "progress": 60,
        "error": "embedding unavailable",
        "created_at": NOW,
        "updated_at": NOW,
        "started_at": NOW,
        "finished_at": None,
    }


def test_get_job_returns_404_when_missing() -> None:
    client = make_client({get_repository: lambda: FakeRepository()})

    response = client.get("/jobs/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found: missing"}


def test_get_documents_returns_indexed_and_uploaded_documents_with_collection_filter() -> None:
    repository = FakeRepository()
    client = make_client({get_repository: lambda: repository})

    response = client.get("/documents", params={"collection": "guides"})

    assert response.status_code == 200
    assert response.json() == {
        "documents": [{**asdict(make_document("doc_1", "guides", DocumentStatus.INDEXED)), "status": "indexed"}]
    }


def test_get_collections_returns_chroma_collection_names() -> None:
    client = make_client({get_vector_store: lambda: FakeVectorStore()})

    response = client.get("/collections")

    assert response.status_code == 200
    assert response.json() == {"collections": ["drafts", "guides"]}


def test_health_returns_ok_when_all_checks_pass() -> None:
    repository = FakeRepository()
    client = make_client(
        {
            get_repository: lambda: repository,
            get_queue_client: lambda: FakeQueueClient(),
            get_vector_store: lambda: FakeVectorStore(),
            get_embedder: lambda: FakeEmbedder(),
        }
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {
            "api": {"status": "ok"},
            "redis": {"status": "ok"},
            "chroma": {"status": "ok"},
            "embedding_api": {"status": "ok"},
            "sqlite": {"status": "ok"},
        },
    }
    assert repository.initialized is True


def test_health_returns_degraded_when_a_check_fails() -> None:
    client = make_client(
        {
            get_repository: lambda: FakeRepository(),
            get_queue_client: lambda: FakeQueueClient(fail=True),
            get_vector_store: lambda: FakeVectorStore(),
            get_embedder: lambda: FakeEmbedder(),
        }
    )

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"]["status"] == "error"
    assert body["checks"]["redis"]["error"] == "redis unavailable"
