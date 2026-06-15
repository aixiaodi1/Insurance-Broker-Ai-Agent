import json

from fastapi.testclient import TestClient

from app.dependencies import get_document_service, get_embedder, get_queue_client, get_rag_query_service, get_repository, get_vector_store
from app.services.rag_query_service import RagQueryService
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


class FailingDocumentService:
    async def upload_files(self, files: list, collection: str) -> dict:
        raise RuntimeError("storage unavailable: fake-secret-token")


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

    def query_chunks(self, collection: str, embedding: list[float], n_results: int = 5) -> list[dict]:
        return [
            {
                "id": "doc_1:0",
                "document": "Insurance responsibility includes the claim context.",
                "metadata": {
                    "collection": collection,
                    "source_file": "guide.txt",
                    "chunk_index": 0,
                    "document_type": "insurance_clause",
                    "section_title": "coverage",
                },
                "distance": 0.12,
            }
        ]


class FailingVectorStore:
    def list_collections(self) -> list[str]:
        raise RuntimeError("chroma unavailable at internal://fake-secret-host")


class FakeEmbedder:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]


class NonCallingEmbedder:
    def __init__(self) -> None:
        self.called = False

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.called = True
        raise AssertionError("embed_texts should not be called")


class FailingHealthEmbedder(NonCallingEmbedder):
    def health_check(self) -> None:
        raise RuntimeError("embedding down at http://fake-secret-host")


def make_client(overrides: dict | None = None) -> TestClient:
    app = create_app()
    for dependency, replacement in (overrides or {}).items():
        app.dependency_overrides[dependency] = replacement
    return TestClient(app)


def expected_public_document(
    document_id: str = "doc_1",
    collection: str = "guides",
    status: DocumentStatus = DocumentStatus.UPLOADED,
) -> dict:
    document = make_document(document_id, collection, status)
    return {
        "document_id": document.id,
        "filename": document.filename,
        "collection": document.collection,
        "status": document.status.value,
        "mime_type": document.mime_type,
        "file_size": document.file_size,
        "chunk_count": document.chunk_count,
        "error": document.error,
        "created_at": document.created_at,
        "indexed_at": document.indexed_at,
    }


def expected_public_job(
    status: JobStatus = JobStatus.RUNNING,
    stage: JobStage = JobStage.EMBEDDING,
    progress: int = 60,
    error: str | None = None,
) -> dict:
    job = make_job(status=status, stage=stage, progress=progress, error=error)
    return {
        "job_id": job.id,
        "document_id": job.document_id,
        "status": job.status.value,
        "stage": job.stage.value,
        "progress": job.progress,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def assert_no_internal_document_fields(payload: dict) -> None:
    assert "id" not in payload
    assert "source_path" not in payload
    assert "text_path" not in payload
    assert "content_hash" not in payload


def assert_no_internal_job_fields(payload: dict) -> None:
    assert "id" not in payload
    assert "rq_job_id" not in payload


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
        "documents": [expected_public_document()],
        "jobs": [expected_public_job(status=JobStatus.QUEUED, stage=JobStage.UPLOADED, progress=5)],
    }
    assert_no_internal_document_fields(response.json()["documents"][0])
    assert_no_internal_job_fields(response.json()["jobs"][0])
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


def test_upload_unexpected_error_returns_generic_503_without_secret() -> None:
    client = make_client({get_document_service: lambda: FailingDocumentService()})

    response = client.post(
        "/documents/upload",
        data={"collection": "guides"},
        files=[("files", ("guide.txt", b"hello world", "text/plain"))],
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Document upload failed"}
    assert "fake-secret-token" not in response.text


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
        "documents": [expected_public_document("doc_1", "guides", DocumentStatus.INDEXED)]
    }
    assert_no_internal_document_fields(response.json()["documents"][0])


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
    assert body["checks"]["redis"]["error"] == "check_failed"
    assert "redis unavailable" not in response.text


def test_health_degraded_errors_do_not_leak_raw_exception_text() -> None:
    client = make_client(
        {
            get_repository: lambda: FakeRepository(),
            get_queue_client: lambda: FakeQueueClient(),
            get_vector_store: lambda: FailingVectorStore(),
            get_embedder: lambda: FakeEmbedder(),
        }
    )

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["chroma"] == {"status": "error", "error": "check_failed"}
    assert "internal://fake-secret-host" not in response.text


def test_health_degrades_when_dependency_constructor_raises_without_leaking_error() -> None:
    app = create_app()

    def raise_vector_store_constructor():
        raise RuntimeError("chroma constructor failed at internal://fake-secret-host")

    app.dependency_overrides[get_repository] = lambda: FakeRepository()
    app.dependency_overrides[get_queue_client] = lambda: FakeQueueClient()
    app.dependency_overrides[get_vector_store] = raise_vector_store_constructor
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["chroma"] == {"status": "error", "error": "check_failed"}
    assert "internal://fake-secret-host" not in response.text


def test_health_degrades_when_repository_constructor_raises_without_leaking_error() -> None:
    app = create_app()

    def raise_repository_constructor():
        raise RuntimeError("sqlite constructor failed at file:///fake-secret-db")

    app.dependency_overrides[get_repository] = raise_repository_constructor
    app.dependency_overrides[get_queue_client] = lambda: FakeQueueClient()
    app.dependency_overrides[get_vector_store] = lambda: FakeVectorStore()
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["sqlite"] == {"status": "error", "error": "check_failed"}
    assert "file:///fake-secret-db" not in response.text


def test_health_embedding_check_does_not_call_embed_texts() -> None:
    embedder = NonCallingEmbedder()
    client = make_client(
        {
            get_repository: lambda: FakeRepository(),
            get_queue_client: lambda: FakeQueueClient(),
            get_vector_store: lambda: FakeVectorStore(),
            get_embedder: lambda: embedder,
        }
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["checks"]["embedding_api"] == {"status": "ok"}
    assert embedder.called is False


def test_health_degrades_when_embedding_health_check_fails_without_leaking_error() -> None:
    embedder = FailingHealthEmbedder()
    client = make_client(
        {
            get_repository: lambda: FakeRepository(),
            get_queue_client: lambda: FakeQueueClient(),
            get_vector_store: lambda: FakeVectorStore(),
            get_embedder: lambda: embedder,
        }
    )

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["embedding_api"] == {"status": "error", "error": "check_failed"}
    assert "fake-secret-host" not in response.text
    assert embedder.called is False


class _AgentTestFakeReranker:
    def rerank(self, query: str, documents: list[str], top_k: int | None = None) -> list[dict]:
        return [{"index": 0, "document": documents[0], "score": 0.91}]


class _AgentTestFakeGenerator:
    def generate(self, prompt: str) -> dict:
        return {"answer": "Insurance responsibility includes the claim context. [1]"}


def test_agent_run_queries_shared_chroma_collection() -> None:
    embedder = FakeEmbedder()
    client = make_client(
        {
            get_embedder: lambda: embedder,
            get_vector_store: lambda: FakeVectorStore(),
            get_rag_query_service: lambda: RagQueryService(
                embedder=embedder,
                vector_store=FakeVectorStore(),
                reranker=_AgentTestFakeReranker(),
                generator=_AgentTestFakeGenerator(),
                retrieval_top_k=20,
                rerank_top_k=5,
                embedding_dimension=1,
            ),
        }
    )

    response = client.post(
        "/agent/run",
        json={
            "prompt": "What can be claimed?",
            "agentId": "research-agent",
            "threadId": "thread_debug",
            "vectorProvider": "chroma",
            "collection": "guides",
            "debug": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "real"
    assert body["status"] == "succeeded"
    assert body["prompt"] == "What can be claimed?"
    assert body["requestJson"]["collection"] == "guides"
    assert body["vectorMatches"][0]["provider"] == "chroma"
    assert body["vectorMatches"][0]["collection"] == "guides"
    assert body["vectorMatches"][0]["metadata"]["document_type"] == "insurance_clause"
    assert body["nodes"][2]["id"] == "retrieve_context"


def test_run_v2_uses_agent_turn_runtime_dependency() -> None:
    from app.dependencies import get_agent_turn_runtime

    class FakeAgentTurnRuntime:
        def run(
            self,
            prompt: str,
            collection: str,
            agent_id: str,
            thread_id: str | None,
            user_id: str = "default",
            collected_vars: dict | None = None,
        ) -> dict:
            return {
                "id": "run_graph",
                "mode": "real",
                "prompt": prompt,
                "status": "succeeded",
                "nodes": [{"id": "graph_node", "status": "succeeded"}],
                "events": [{"id": "evt_graph_node", "nodeId": "graph_node"}],
                "toolCalls": [],
                "vectorMatches": [],
                "requestJson": {"prompt": prompt},
                "responseJson": {"collection": collection, "userId": user_id},
                "finalAnswer": "graph answer",
            }

    client = make_client({get_agent_turn_runtime: lambda: FakeAgentTurnRuntime()})

    response = client.post(
        "/agent/run_v2",
        json={
            "prompt": "等待期是多少",
            "agentId": "research-agent",
            "threadId": "thread_graph",
            "collection": "guides",
            "userId": "user_graph",
            "collectedVars": {"age": 30},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "run_graph"
    assert body["finalAnswer"] == "graph answer"
    assert body["nodes"][0]["id"] == "graph_node"
    assert body["responseJson"] == {"collection": "guides", "userId": "user_graph"}


def test_run_v2_stream_uses_agent_turn_runtime_stream_dependency() -> None:
    from app.dependencies import get_agent_turn_runtime

    class FakeAgentTurnRuntime:
        def stream(
            self,
            prompt: str,
            collection: str,
            agent_id: str,
            thread_id: str | None,
            user_id: str = "default",
            collected_vars: dict | None = None,
        ):
            yield {"type": "run_started", "summary": prompt}
            yield {
                "type": "run_finished",
                "run": {
                    "id": "run_stream",
                    "mode": "real",
                    "prompt": prompt,
                    "status": "succeeded",
                    "nodes": [],
                    "events": [],
                    "toolCalls": [],
                    "vectorMatches": [],
                    "requestJson": {"prompt": prompt},
                    "responseJson": {"collection": collection, "userId": user_id},
                    "finalAnswer": "stream answer",
                },
            }

    client = make_client({get_agent_turn_runtime: lambda: FakeAgentTurnRuntime()})

    with client.stream(
        "POST",
        "/agent/run_v2/stream",
        json={
            "prompt": "hello",
            "agentId": "research-agent",
            "threadId": "thread_stream",
            "collection": "guides",
            "userId": "user_stream",
        },
    ) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in body.splitlines() if line.strip()]
    assert [line["type"] for line in lines] == ["run_started", "run_finished"]
    assert lines[-1]["run"]["finalAnswer"] == "stream answer"


def test_run_v2_non_stream_response_exposes_transparent_events() -> None:
    from app.dependencies import get_agent_turn_runtime

    class FakeAgentTurnRuntime:
        def run(
            self,
            prompt: str,
            collection: str,
            agent_id: str,
            thread_id: str | None,
            user_id: str = "default",
            collected_vars: dict | None = None,
        ) -> dict:
            return {
                "id": "run_transparent",
                "mode": "real",
                "prompt": prompt,
                "status": "succeeded",
                "nodes": [],
                "events": [],
                "toolCalls": [],
                "vectorMatches": [],
                "requestJson": {"prompt": prompt},
                "responseJson": {
                    "agentRuntime": {"controlMode": "llm_react"},
                    "publicPlanning": {"intent_anchor": {"user_goal": "show process"}},
                    "streamEvents": [
                        {"type": "run_started", "summary": "started"},
                        {"type": "context_loaded", "summary": "context"},
                        {"type": "intent_anchor", "summary": "show process"},
                        {"type": "task_decomposition", "summary": "1 tasks planned."},
                        {"type": "final_answer", "summary": "Final answer generated.", "finalAnswer": "answer"},
                        {"type": "run_finished", "summary": "finished"},
                    ],
                },
                "finalAnswer": "answer",
            }

    client = make_client({get_agent_turn_runtime: lambda: FakeAgentTurnRuntime()})

    response = client.post(
        "/agent/run_v2",
        json={
            "prompt": "show process",
            "agentId": "research-agent",
            "threadId": "thread_transparent",
            "collection": "guides",
            "userId": "user_transparent",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["responseJson"]["agentRuntime"]["controlMode"] == "llm_react"
    assert body["responseJson"]["publicPlanning"]["intent_anchor"]["user_goal"] == "show process"
    assert [event["type"] for event in body["responseJson"]["streamEvents"]] == [
        "run_started",
        "context_loaded",
        "intent_anchor",
        "task_decomposition",
        "final_answer",
        "run_finished",
    ]
