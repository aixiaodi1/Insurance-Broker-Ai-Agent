# RAG Backend Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent FastAPI RAG ingestion backend that uploads `.txt`, `.md`, and `.pdf` files, queues ingestion through Redis/RQ, embeds chunks through the local Embedding API, and writes vectors into local persistent ChromaDB.

**Architecture:** The backend lives under `rag-backend/` and uses thin FastAPI routers, service-layer orchestration, and infrastructure adapters for SQLite, Redis/RQ, ChromaDB, parsers, chunking, and the local Embedding API. The management page is a small FastAPI-rendered HTML page with native JavaScript for upload, job polling, and document listing. The existing LangGraph trace frontend is not changed.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic Settings, SQLite, Redis, RQ, ChromaDB, httpx, pypdf, pytest, pytest-httpx, python-multipart, Jinja2.

---

## File Structure

- Create `rag-backend/pyproject.toml`, `rag-backend/.env.example`, `rag-backend/README.md`.
- Modify root `.gitignore` to ignore Python caches, local virtualenvs, and `rag-backend/data/`.
- Create `rag-backend/app/__init__.py`, `rag-backend/app/main.py`, `rag-backend/app/config.py`, `rag-backend/app/dependencies.py`, `rag-backend/app/domain.py`, `rag-backend/app/errors.py`.
- Create routers: `rag-backend/app/routers/admin.py`, `rag-backend/app/routers/collections.py`, `rag-backend/app/routers/documents.py`, `rag-backend/app/routers/health.py`, `rag-backend/app/routers/ingestion_jobs.py`.
- Create services: `rag-backend/app/services/document_service.py`, `rag-backend/app/services/ingestion_service.py`, `rag-backend/app/services/job_service.py`.
- Create embeddings: `rag-backend/app/infrastructure/embeddings/base.py`, `rag-backend/app/infrastructure/embeddings/local_api.py`.
- Create vector stores: `rag-backend/app/infrastructure/vectorstores/base.py`, `rag-backend/app/infrastructure/vectorstores/chroma_store.py`.
- Create parsers: `rag-backend/app/infrastructure/parsers/base.py`, `rag-backend/app/infrastructure/parsers/text_parser.py`, `rag-backend/app/infrastructure/parsers/markdown_parser.py`, `rag-backend/app/infrastructure/parsers/pdf_parser.py`, `rag-backend/app/infrastructure/parsers/registry.py`.
- Create chunkers: `rag-backend/app/infrastructure/chunkers/base.py`, `rag-backend/app/infrastructure/chunkers/recursive.py`.
- Create queue adapter: `rag-backend/app/infrastructure/queue/base.py`, `rag-backend/app/infrastructure/queue/rq_queue.py`.
- Create repository: `rag-backend/app/infrastructure/repositories/base.py`, `rag-backend/app/infrastructure/repositories/sqlite.py`.
- Create worker: `rag-backend/app/workers/ingest_worker.py`.
- Create admin assets: `rag-backend/app/templates/admin.html`, `rag-backend/app/static/admin.css`, `rag-backend/app/static/admin.js`.
- Create tests under `rag-backend/tests/` matching the implementation folders.

## Reference Notes

- ChromaDB official docs: [Add data to a collection](https://docs.trychroma.com/docs/collections/add-data) shows `collection.add(ids=..., embeddings=..., documents=..., metadatas=...)` and requires unique string IDs for inserted records.
- RQ official docs: [Exceptions and retries](https://python-rq.org/docs/exceptions/) supports retrying failed jobs with `Retry(max=3, interval=[10, 30, 60])`.

## Task 1: Scaffold Python Backend and Configuration

**Files:**
- Create: `rag-backend/pyproject.toml`
- Create: `rag-backend/.env.example`
- Create: `rag-backend/README.md`
- Create: `rag-backend/app/__init__.py`
- Create: `rag-backend/app/config.py`
- Create: `rag-backend/app/main.py`
- Create: `rag-backend/app/errors.py`
- Modify: `.gitignore`
- Test: `rag-backend/tests/test_config.py`

- [ ] **Step 1: Create a failing configuration test**

Create `rag-backend/tests/test_config.py`:

```python
from pathlib import Path

from app.config import Settings


def test_settings_defaults_are_local_and_safe(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'rag.sqlite'}",
        upload_dir=tmp_path / "uploads",
        chroma_persist_dir=tmp_path / "chroma",
        embedding_api_base_url="http://localhost:9000",
    )

    assert settings.app_env == "local"
    assert settings.chunk_size == 500
    assert settings.chunk_overlap == 50
    assert settings.embedding_model == "embo-01"
    assert settings.embedding_api_key == ""
    assert settings.minimax_api_key == ""
    assert settings.allowed_extensions == [".txt", ".md", ".pdf"]
```

Run: `cd rag-backend; python -m pytest tests/test_config.py -v`

Expected: FAIL because `app.config` does not exist.

- [ ] **Step 2: Create project metadata and dependencies**

Create `rag-backend/pyproject.toml`:

```toml
[project]
name = "rag-backend"
version = "0.1.0"
description = "FastAPI RAG ingestion backend for ChromaDB"
requires-python = ">=3.11"
dependencies = [
  "chromadb",
  "fastapi",
  "httpx",
  "jinja2",
  "pydantic-settings",
  "pypdf",
  "python-multipart",
  "redis",
  "rq",
  "uvicorn[standard]"
]

[project.optional-dependencies]
dev = [
  "pytest",
  "pytest-httpx"
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 3: Add safe environment example**

Create `rag-backend/.env.example`:

```env
APP_ENV=local
DATABASE_URL=sqlite:///./data/rag.sqlite

UPLOAD_DIR=./data/uploads
CHROMA_PERSIST_DIR=./data/chroma

REDIS_URL=redis://localhost:6379/0
RQ_QUEUE_NAME=rag-ingestion

EMBEDDING_API_BASE_URL=http://localhost:9000
EMBEDDING_API_PATH=/v1/embeddings
EMBEDDING_API_KEY=
MINIMAX_API_KEY=
EMBEDDING_MODEL=embo-01
EMBEDDING_DIMENSION=1024
EMBEDDING_BATCH_SIZE=32

CHUNK_SIZE=500
CHUNK_OVERLAP=50
MAX_UPLOAD_MB=50
ALLOWED_EXTENSIONS=.txt,.md,.pdf
```

- [ ] **Step 4: Implement settings**

Create `rag-backend/app/__init__.py` as an empty package marker.

Create `rag-backend/app/config.py`:

```python
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    database_url: str = "sqlite:///./data/rag.sqlite"
    upload_dir: Path = Path("./data/uploads")
    chroma_persist_dir: Path = Path("./data/chroma")
    redis_url: str = "redis://localhost:6379/0"
    rq_queue_name: str = "rag-ingestion"
    embedding_api_base_url: str = "http://localhost:9000"
    embedding_api_path: str = "/v1/embeddings"
    embedding_api_key: str = ""
    minimax_api_key: str = ""
    embedding_model: str = "embo-01"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 32
    chunk_size: int = 500
    chunk_overlap: int = 50
    max_upload_mb: int = 50
    allowed_extensions: list[str] = Field(default_factory=lambda: [".txt", ".md", ".pdf"])

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def parse_extensions(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Create `rag-backend/app/errors.py`:

```python
class RagBackendError(Exception):
    """Base exception for expected RAG backend failures."""


class ValidationError(RagBackendError):
    """Raised when user input cannot be accepted."""


class RetryableIngestionError(RagBackendError):
    """Raised when RQ should retry the ingestion job."""


class NonRetryableIngestionError(RagBackendError):
    """Raised when retrying cannot fix the ingestion job."""
```

Create `rag-backend/app/main.py`:

```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Backend Ingestion", version="0.1.0")
    return app


app = create_app()
```

- [ ] **Step 5: Update root ignore rules**

Append to root `.gitignore`:

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
rag-backend/.venv/
rag-backend/data/
```

- [ ] **Step 6: Verify configuration test passes**

Run: `cd rag-backend; python -m pytest tests/test_config.py -v`

Expected: PASS.

- [ ] **Step 7: Commit scaffold**

```bash
git add .gitignore rag-backend
git commit -m "feat: scaffold rag backend"
```

## Task 2: Domain Models and SQLite Repository

**Files:**
- Create: `rag-backend/app/domain.py`
- Create: `rag-backend/app/infrastructure/repositories/base.py`
- Create: `rag-backend/app/infrastructure/repositories/sqlite.py`
- Test: `rag-backend/tests/test_sqlite_repository.py`

- [ ] **Step 1: Write failing repository tests**

Create `rag-backend/tests/test_sqlite_repository.py`:

```python
from pathlib import Path

from app.domain import DocumentStatus, JobStage, JobStatus
from app.infrastructure.repositories.sqlite import SQLiteRepository


def test_repository_creates_document_job_and_chunks(tmp_path: Path) -> None:
    repo = SQLiteRepository(f"sqlite:///{tmp_path / 'rag.sqlite'}")
    repo.initialize()

    document = repo.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=12,
        source_path=str(tmp_path / "guide.md"),
        content_hash="abc123",
    )
    job = repo.create_job(document_id=document.id, collection="docs")

    repo.mark_document_indexing(document.id)
    repo.update_job(job.id, status=JobStatus.RUNNING, stage=JobStage.EMBEDDING, progress=65)
    repo.add_chunks(
        document_id=document.id,
        collection="docs",
        chunks=[
            {
                "chunk_index": 0,
                "chroma_id": f"{document.id}:0",
                "content_preview": "hello",
                "token_count": 1,
                "source_file": "guide.md",
                "upload_time": document.created_at,
            }
        ],
    )
    repo.mark_document_indexed(document.id, chunk_count=1)
    repo.update_job(job.id, status=JobStatus.SUCCEEDED, stage=JobStage.DONE, progress=100)

    stored_document = repo.get_document(document.id)
    stored_job = repo.get_job(job.id)

    assert stored_document.status == DocumentStatus.INDEXED
    assert stored_document.chunk_count == 1
    assert stored_job.status == JobStatus.SUCCEEDED
    assert repo.list_documents(collection="docs")[0].filename == "guide.md"
```

Run: `cd rag-backend; python -m pytest tests/test_sqlite_repository.py -v`

Expected: FAIL because repository modules do not exist.

- [ ] **Step 2: Implement domain records**

Create `rag-backend/app/domain.py`:

```python
from dataclasses import dataclass
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
```

- [ ] **Step 3: Define repository protocol**

Create `rag-backend/app/infrastructure/repositories/base.py`:

```python
from typing import Protocol

from app.domain import DocumentRecord, JobRecord, JobStage, JobStatus


class Repository(Protocol):
    def initialize(self) -> None: ...
    def create_document(self, filename: str, collection: str, mime_type: str, file_size: int, source_path: str, content_hash: str) -> DocumentRecord: ...
    def get_document(self, document_id: str) -> DocumentRecord: ...
    def list_documents(self, collection: str | None = None) -> list[DocumentRecord]: ...
    def mark_document_indexing(self, document_id: str) -> None: ...
    def mark_document_indexed(self, document_id: str, chunk_count: int) -> None: ...
    def mark_document_failed(self, document_id: str, error: str) -> None: ...
    def set_document_text_path(self, document_id: str, text_path: str) -> None: ...
    def create_job(self, document_id: str, collection: str) -> JobRecord: ...
    def set_job_rq_id(self, job_id: str, rq_job_id: str) -> None: ...
    def get_job(self, job_id: str) -> JobRecord: ...
    def get_job_by_rq_id(self, rq_job_id: str) -> JobRecord: ...
    def update_job(self, job_id: str, status: JobStatus, stage: JobStage, progress: int, error: str | None = None) -> None: ...
    def add_chunks(self, document_id: str, collection: str, chunks: list[dict]) -> None: ...
```

- [ ] **Step 4: Implement SQLite repository**

Create `rag-backend/app/infrastructure/repositories/sqlite.py` with `sqlite3`, UUID ids prefixed as `doc_` and `job_`, ISO timestamps, schema creation for `documents`, `ingestion_jobs`, and `chunks`, row-to-dataclass mappers, and every method from the protocol. Use `Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)` before connecting.

Implementation requirements:

```python
documents.status starts as "uploaded"
ingestion_jobs.status starts as "queued"
ingestion_jobs.stage starts as "uploaded"
ingestion_jobs.progress starts as 5
mark_document_indexed sets indexed_at to current ISO timestamp
update_job sets updated_at every time
update_job sets started_at when status becomes running and started_at is empty
update_job sets finished_at when status becomes succeeded or failed
```

- [ ] **Step 5: Verify repository tests pass**

Run: `cd rag-backend; python -m pytest tests/test_sqlite_repository.py -v`

Expected: PASS.

- [ ] **Step 6: Commit repository**

```bash
git add rag-backend/app/domain.py rag-backend/app/infrastructure/repositories rag-backend/tests/test_sqlite_repository.py
git commit -m "feat: add rag metadata repository"
```

## Task 3: Parsers and Recursive Chunker

**Files:**
- Create: `rag-backend/app/infrastructure/parsers/base.py`
- Create: `rag-backend/app/infrastructure/parsers/text_parser.py`
- Create: `rag-backend/app/infrastructure/parsers/markdown_parser.py`
- Create: `rag-backend/app/infrastructure/parsers/pdf_parser.py`
- Create: `rag-backend/app/infrastructure/parsers/registry.py`
- Create: `rag-backend/app/infrastructure/chunkers/base.py`
- Create: `rag-backend/app/infrastructure/chunkers/recursive.py`
- Test: `rag-backend/tests/test_parsers_and_chunker.py`

- [ ] **Step 1: Write failing parser and chunker tests**

Create `rag-backend/tests/test_parsers_and_chunker.py`:

```python
from pathlib import Path

import pytest

from app.infrastructure.chunkers.recursive import RecursiveTextChunker
from app.infrastructure.parsers.registry import ParserRegistry


def test_text_and_markdown_parsers_extract_text(tmp_path: Path) -> None:
    txt = tmp_path / "note.txt"
    md = tmp_path / "note.md"
    txt.write_text("plain text", encoding="utf-8")
    md.write_text("# Title\n\nmarkdown text", encoding="utf-8")

    registry = ParserRegistry.default()

    assert registry.parse(txt) == "plain text"
    assert "markdown text" in registry.parse(md)


def test_registry_rejects_unsupported_extension(tmp_path: Path) -> None:
    file_path = tmp_path / "table.xlsx"
    file_path.write_text("not supported", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file extension"):
        ParserRegistry.default().parse(file_path)


def test_recursive_chunker_defaults_to_500_with_50_overlap() -> None:
    text = " ".join(str(index) for index in range(650))
    chunker = RecursiveTextChunker()
    chunks = chunker.split(text)

    assert chunker.chunk_size == 500
    assert chunker.chunk_overlap == 50
    assert chunks[0].chunk_index == 0
    assert len(chunks) >= 2
    assert chunks[0].token_count <= 500
```

Run: `cd rag-backend; python -m pytest tests/test_parsers_and_chunker.py -v`

Expected: FAIL because parser and chunker modules do not exist.

- [ ] **Step 2: Implement parser protocols and registry**

Create parser files with these behaviors:

```python
DocumentParser.parse(path: Path) -> str
TextParser reads UTF-8 text
MarkdownParser reads UTF-8 text without transforming markdown
PdfParser uses pypdf.PdfReader and joins page.extract_text() values with newlines
ParserRegistry.default() maps ".txt", ".md", ".pdf"
ParserRegistry.parse(path) raises ValueError("Unsupported file extension: .ext") for unknown extensions
```

- [ ] **Step 3: Implement chunker protocol and recursive chunker**

Create `RecursiveTextChunker` with:

```python
chunk_size default: 500
chunk_overlap default: 50
split(text) normalizes whitespace
split(text) raises ValueError("Cannot chunk empty text") for empty content
split(text) returns list[TextChunk]
token_count uses whitespace token count
overlap is applied by reusing the last 50 tokens from the previous chunk
```

- [ ] **Step 4: Verify parser and chunker tests pass**

Run: `cd rag-backend; python -m pytest tests/test_parsers_and_chunker.py -v`

Expected: PASS.

- [ ] **Step 5: Commit parsers and chunker**

```bash
git add rag-backend/app/infrastructure/parsers rag-backend/app/infrastructure/chunkers rag-backend/tests/test_parsers_and_chunker.py
git commit -m "feat: add parsers and text chunker"
```

## Task 4: Local Embedding API Adapter

**Files:**
- Create: `rag-backend/app/infrastructure/embeddings/base.py`
- Create: `rag-backend/app/infrastructure/embeddings/local_api.py`
- Test: `rag-backend/tests/test_local_embedding_provider.py`

- [ ] **Step 1: Write failing embedding adapter tests**

Create `rag-backend/tests/test_local_embedding_provider.py`:

```python
import httpx

from app.infrastructure.embeddings.local_api import LocalApiEmbeddingProvider


def test_local_embedding_provider_reads_key_and_validates_dimension(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]},
    )
    provider = LocalApiEmbeddingProvider(
        base_url="http://localhost:9000",
        path="/v1/embeddings",
        api_key="secret",
        model="embo-01",
        dimension=3,
        batch_size=32,
    )

    embeddings = provider.embed_texts(["alpha", "beta"])
    request = httpx_mock.get_request()

    assert embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.read() == b'{"model":"embo-01","input":["alpha","beta"]}'


def test_local_embedding_provider_accepts_embeddings_response_shape(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"embeddings": [[0.1, 0.2, 0.3]]},
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    assert provider.embed_texts(["alpha"]) == [[0.1, 0.2, 0.3]]
```

Run: `cd rag-backend; python -m pytest tests/test_local_embedding_provider.py -v`

Expected: FAIL because embedding modules do not exist.

- [ ] **Step 2: Define embedding protocol**

Create `rag-backend/app/infrastructure/embeddings/base.py`:

```python
from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
```

- [ ] **Step 3: Implement local API adapter**

Create `rag-backend/app/infrastructure/embeddings/local_api.py`:

```python
import httpx

from app.errors import RetryableIngestionError, NonRetryableIngestionError


class LocalApiEmbeddingProvider:
    def __init__(self, base_url: str, path: str, api_key: str, model: str, dimension: int, batch_size: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.path = path if path.startswith("/") else f"/{path}"
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.batch_size = batch_size

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            embeddings.extend(self._embed_batch(texts[start : start + self.batch_size]))
        return embeddings

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = httpx.post(
                f"{self.base_url}{self.path}",
                headers=headers,
                json={"model": self.model, "input": texts},
                timeout=60,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RetryableIngestionError(f"Embedding API request failed: {exc}") from exc

        vectors = self._extract_embeddings(response.json())
        for vector in vectors:
            if len(vector) != self.dimension:
                raise NonRetryableIngestionError(
                    f"Embedding dimension mismatch: expected {self.dimension}, got {len(vector)}"
                )
        return vectors

    def _extract_embeddings(self, payload: dict) -> list[list[float]]:
        if isinstance(payload.get("embeddings"), list):
            return payload["embeddings"]
        if isinstance(payload.get("data"), list):
            return [item["embedding"] for item in payload["data"]]
        raise NonRetryableIngestionError("Embedding API response did not include embeddings")
```

- [ ] **Step 4: Verify embedding tests pass**

Run: `cd rag-backend; python -m pytest tests/test_local_embedding_provider.py -v`

Expected: PASS.

- [ ] **Step 5: Commit embedding adapter**

```bash
git add rag-backend/app/infrastructure/embeddings rag-backend/tests/test_local_embedding_provider.py
git commit -m "feat: add local embedding provider"
```

## Task 5: ChromaDB Vector Store Adapter

**Files:**
- Create: `rag-backend/app/infrastructure/vectorstores/base.py`
- Create: `rag-backend/app/infrastructure/vectorstores/chroma_store.py`
- Test: `rag-backend/tests/test_chroma_vector_store.py`

- [ ] **Step 1: Write failing Chroma tests**

Create `rag-backend/tests/test_chroma_vector_store.py`:

```python
from pathlib import Path

from app.infrastructure.vectorstores.chroma_store import ChromaVectorStore


def test_chroma_store_adds_chunks_with_metadata(tmp_path: Path) -> None:
    store = ChromaVectorStore(tmp_path / "chroma")
    store.ensure_collection("docs")
    store.add_chunks(
        collection="docs",
        ids=["doc_1:0"],
        texts=["hello chroma"],
        embeddings=[[0.1, 0.2, 0.3]],
        metadatas=[
            {
                "document_id": "doc_1",
                "filename": "guide.md",
                "source_file": "guide.md",
                "collection": "docs",
                "chunk_index": 0,
                "upload_time": "2026-05-24T10:00:00+08:00",
                "source": "upload",
                "content_hash": "abc",
            }
        ],
    )

    collection = store.client.get_collection("docs")
    result = collection.get(ids=["doc_1:0"], include=["documents", "metadatas"])

    assert result["documents"] == ["hello chroma"]
    assert result["metadatas"][0]["source_file"] == "guide.md"
    assert result["metadatas"][0]["chunk_index"] == 0
```

Run: `cd rag-backend; python -m pytest tests/test_chroma_vector_store.py -v`

Expected: FAIL because vector store modules do not exist.

- [ ] **Step 2: Define vector store protocol**

Create `rag-backend/app/infrastructure/vectorstores/base.py`:

```python
from typing import Protocol


class VectorStore(Protocol):
    def ensure_collection(self, name: str) -> None: ...
    def list_collections(self) -> list[str]: ...
    def add_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None: ...
```

- [ ] **Step 3: Implement Chroma vector store**

Create `rag-backend/app/infrastructure/vectorstores/chroma_store.py`:

```python
from pathlib import Path

import chromadb

from app.errors import RetryableIngestionError


class ChromaVectorStore:
    def __init__(self, persist_dir: Path) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_dir))

    def ensure_collection(self, name: str) -> None:
        self.client.get_or_create_collection(name=name)

    def list_collections(self) -> list[str]:
        return sorted(collection.name for collection in self.client.list_collections())

    def add_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        try:
            target = self.client.get_or_create_collection(name=collection)
            target.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)
        except Exception as exc:
            raise RetryableIngestionError(f"Chroma write failed: {exc}") from exc
```

- [ ] **Step 4: Verify Chroma tests pass**

Run: `cd rag-backend; python -m pytest tests/test_chroma_vector_store.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Chroma adapter**

```bash
git add rag-backend/app/infrastructure/vectorstores rag-backend/tests/test_chroma_vector_store.py
git commit -m "feat: add chroma vector store"
```

## Task 6: Services for Upload, Jobs, and Ingestion

**Files:**
- Create: `rag-backend/app/services/job_service.py`
- Create: `rag-backend/app/services/document_service.py`
- Create: `rag-backend/app/services/ingestion_service.py`
- Test: `rag-backend/tests/test_services.py`

- [ ] **Step 1: Write failing service tests with fakes**

Create `rag-backend/tests/test_services.py` with fake repository, fake queue, fake parser, fake chunker, fake embedder, and fake vector store. Cover:

```python
DocumentService.upload_files saves files, creates documents, creates jobs, and enqueues RQ work
IngestionService.ingest_document updates job stages parsing -> chunking -> embedding -> writing -> done
IngestionService writes chroma ids as "{document_id}:{chunk_index}"
IngestionService metadata includes source_file, chunk_index, upload_time
IngestionService marks empty parsed text as failed without retry
```

Run: `cd rag-backend; python -m pytest tests/test_services.py -v`

Expected: FAIL because service modules do not exist.

- [ ] **Step 2: Implement JobService**

Create `rag-backend/app/services/job_service.py` with methods:

```python
create_job(document_id, collection)
attach_rq_job(job_id, rq_job_id)
get_job(job_id)
get_job_by_rq_id(rq_job_id)
mark_running(job_id, stage, progress)
update_progress(job_id, stage, progress)
mark_succeeded(job_id)
mark_failed(job_id, error)
```

Map final success to `JobStatus.SUCCEEDED`, `JobStage.DONE`, `progress=100`. Map final failure to `JobStatus.FAILED` and preserve the current stage.

- [ ] **Step 3: Implement DocumentService**

Create `rag-backend/app/services/document_service.py` with:

```python
upload_files(files, collection) -> dict
```

Implementation requirements:

```python
strip and validate collection
validate extensions against settings.allowed_extensions
validate file size against settings.max_upload_mb
save original file under upload_dir / document_id / original.ext
create sha256 content_hash
create document record
create ingestion job
enqueue ingestion through queue client
store returned rq_job_id on the job record
return {"documents": [...], "jobs": [...]}
```

- [ ] **Step 4: Implement IngestionService**

Create `rag-backend/app/services/ingestion_service.py` with:

```python
ingest_document(job_id, document_id, collection) -> None
```

Implementation requirements:

```python
mark document indexing and job parsing at 20
parse original file
raise NonRetryableIngestionError for empty text
write extracted.txt and set document text_path
chunk text and mark chunking at 35
embed chunks and mark embedding at 65
build chroma ids as "{document_id}:{chunk_index}"
build metadata with document_id, filename, source_file, collection, chunk_index, upload_time, source, content_hash
write to vector store and mark writing at 90
record chunks in SQLite
mark document indexed with chunk_count
mark job succeeded
on NonRetryableIngestionError, mark document and job failed, then re-raise
on RetryableIngestionError, write current error to job, then re-raise so RQ retry policy can run
```

- [ ] **Step 5: Verify service tests pass**

Run: `cd rag-backend; python -m pytest tests/test_services.py -v`

Expected: PASS.

- [ ] **Step 6: Commit services**

```bash
git add rag-backend/app/services rag-backend/tests/test_services.py
git commit -m "feat: add ingestion services"
```

## Task 7: Redis/RQ Queue and Worker

**Files:**
- Create: `rag-backend/app/infrastructure/queue/base.py`
- Create: `rag-backend/app/infrastructure/queue/rq_queue.py`
- Create: `rag-backend/app/workers/ingest_worker.py`
- Modify: `rag-backend/app/dependencies.py`
- Test: `rag-backend/tests/test_queue_adapter.py`
- Test: `rag-backend/tests/test_worker.py`

- [ ] **Step 1: Write failing queue and worker tests**

Create tests that monkeypatch RQ and `get_current_job` to verify:

```python
RqQueueClient.enqueue_ingestion enqueues app.workers.ingest_worker.ingest_document_job
RqQueueClient uses Retry(max=3, interval=[10, 30, 60])
worker resolves current RQ job id
worker loads the matching ingestion job through JobService
worker calls IngestionService.ingest_document(job_id, document_id, collection)
```

Run: `cd rag-backend; python -m pytest tests/test_queue_adapter.py tests/test_worker.py -v`

Expected: FAIL because queue and worker modules do not exist.

- [ ] **Step 2: Define queue protocol**

Create `rag-backend/app/infrastructure/queue/base.py`:

```python
from typing import Protocol


class QueueClient(Protocol):
    def enqueue_ingestion(self, document_id: str, collection: str) -> str: ...
```

- [ ] **Step 3: Implement RQ adapter**

Create `rag-backend/app/infrastructure/queue/rq_queue.py`:

```python
from redis import Redis
from rq import Queue, Retry


class RqQueueClient:
    def __init__(self, redis_url: str, queue_name: str) -> None:
        self.redis = Redis.from_url(redis_url)
        self.queue = Queue(queue_name, connection=self.redis)

    def enqueue_ingestion(self, document_id: str, collection: str) -> str:
        job = self.queue.enqueue(
            "app.workers.ingest_worker.ingest_document_job",
            document_id,
            collection,
            retry=Retry(max=3, interval=[10, 30, 60]),
            job_timeout="30m",
            failure_ttl=86400,
        )
        return job.id
```

- [ ] **Step 4: Implement dependency factory**

Create `rag-backend/app/dependencies.py` with factories for settings, repository, parser registry, chunker, embedder, vector store, queue client, job service, document service, and ingestion service. Ensure `repository.initialize()` runs before services are returned.

- [ ] **Step 5: Implement worker**

Create `rag-backend/app/workers/ingest_worker.py`:

```python
import logging

from rq import get_current_job

from app.dependencies import get_ingestion_service, get_job_service

logger = logging.getLogger(__name__)


def ingest_document_job(document_id: str, collection: str) -> None:
    rq_job = get_current_job()
    if rq_job is None:
        raise RuntimeError("ingest_document_job must run inside an RQ worker")

    job_service = get_job_service()
    app_job = job_service.get_job_by_rq_id(rq_job.id)
    ingestion_service = get_ingestion_service()

    try:
        ingestion_service.ingest_document(app_job.id, document_id, collection)
    except Exception:
        logger.exception("Ingestion job failed", extra={"job_id": app_job.id, "document_id": document_id})
        raise
```

- [ ] **Step 6: Verify queue and worker tests pass**

Run: `cd rag-backend; python -m pytest tests/test_queue_adapter.py tests/test_worker.py -v`

Expected: PASS.

- [ ] **Step 7: Commit queue and worker**

```bash
git add rag-backend/app/infrastructure/queue rag-backend/app/workers rag-backend/app/dependencies.py rag-backend/tests/test_queue_adapter.py rag-backend/tests/test_worker.py
git commit -m "feat: add rq ingestion worker"
```

## Task 8: FastAPI Routers and API Contracts

**Files:**
- Create: `rag-backend/app/routers/documents.py`
- Create: `rag-backend/app/routers/ingestion_jobs.py`
- Create: `rag-backend/app/routers/collections.py`
- Create: `rag-backend/app/routers/health.py`
- Modify: `rag-backend/app/main.py`
- Test: `rag-backend/tests/test_api_routes.py`

- [ ] **Step 1: Write failing API route tests**

Create `rag-backend/tests/test_api_routes.py` using `fastapi.testclient.TestClient` and dependency overrides. Cover:

```python
POST /documents/upload returns documents and jobs for a .txt upload
POST /documents/upload rejects .xlsx with 400
GET /jobs/{job_id} returns status, stage, progress, and error
GET /documents returns indexed documents and supports collection filter
GET /collections returns Chroma collection names
GET /health returns status and checks for api, redis, chroma, embedding_api, sqlite
```

Run: `cd rag-backend; python -m pytest tests/test_api_routes.py -v`

Expected: FAIL because routers are not implemented.

- [ ] **Step 2: Implement document upload router**

Create `rag-backend/app/routers/documents.py`:

```python
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.dependencies import get_document_service, get_repository
from app.errors import ValidationError

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    collection: str = Form(...),
    service=Depends(get_document_service),
):
    try:
        return await service.upload_files(files, collection)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_documents(collection: str | None = None, repository=Depends(get_repository)):
    return {"documents": [document.__dict__ for document in repository.list_documents(collection=collection)]}
```

- [ ] **Step 3: Implement job, collections, and health routers**

Implement:

```python
GET /jobs/{job_id} -> {"job_id": ..., "document_id": ..., "status": ..., "stage": ..., "progress": ..., "error": ..., timestamps...}
GET /collections -> {"collections": vector_store.list_collections()}
GET /health -> check sqlite initialize, Redis ping, Chroma writable directory, and embedding API base URL configured
```

For `/health`, return HTTP 200 with `status: "ok"` when all checks pass and `status: "degraded"` when one check fails.

- [ ] **Step 4: Wire routers in FastAPI app**

Modify `rag-backend/app/main.py`:

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import admin, collections, documents, health, ingestion_jobs


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Backend Ingestion", version="0.1.0")
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(health.router)
    app.include_router(collections.router)
    app.include_router(documents.router)
    app.include_router(ingestion_jobs.router)
    app.include_router(admin.router)
    return app


app = create_app()
```

- [ ] **Step 5: Verify API route tests pass**

Run: `cd rag-backend; python -m pytest tests/test_api_routes.py -v`

Expected: PASS.

- [ ] **Step 6: Commit API routes**

```bash
git add rag-backend/app/routers rag-backend/app/main.py rag-backend/tests/test_api_routes.py
git commit -m "feat: add rag ingestion api routes"
```

## Task 9: FastAPI Management Page

**Files:**
- Create: `rag-backend/app/routers/admin.py`
- Create: `rag-backend/app/templates/admin.html`
- Create: `rag-backend/app/static/admin.css`
- Create: `rag-backend/app/static/admin.js`
- Test: `rag-backend/tests/test_admin_page.py`

- [ ] **Step 1: Write failing admin page tests**

Create `rag-backend/tests/test_admin_page.py`:

```python
from fastapi.testclient import TestClient

from app.main import create_app


def test_admin_page_contains_three_required_areas() -> None:
    client = TestClient(create_app())
    response = client.get("/admin")

    assert response.status_code == 200
    assert "上传区" in response.text
    assert "任务区" in response.text
    assert "文档区" in response.text
    assert "/documents/upload" in response.text
    assert "/jobs/" in response.text
    assert "/documents" in response.text
```

Run: `cd rag-backend; python -m pytest tests/test_admin_page.py -v`

Expected: FAIL because admin router/template are missing.

- [ ] **Step 2: Implement admin router**

Create `rag-backend/app/routers/admin.py`:

```python
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["admin"])


@router.get("/admin", response_class=HTMLResponse)
def admin_page() -> str:
    return Path("app/templates/admin.html").read_text(encoding="utf-8")
```

- [ ] **Step 3: Implement admin HTML**

Create `rag-backend/app/templates/admin.html` with three sections:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>RAG 后端管理页</title>
    <link rel="stylesheet" href="/static/admin.css" />
  </head>
  <body>
    <main class="shell">
      <section class="panel" id="upload-panel">
        <h1>上传区</h1>
        <form id="upload-form">
          <input id="collection" name="collection" value="default" />
          <input id="files" name="files" type="file" accept=".txt,.md,.pdf" multiple />
          <button type="submit">上传并入库</button>
        </form>
        <pre id="upload-result"></pre>
      </section>
      <section class="panel" id="jobs-panel">
        <h2>任务区</h2>
        <div id="jobs"></div>
      </section>
      <section class="panel" id="documents-panel">
        <h2>文档区</h2>
        <button id="refresh-documents">刷新文档</button>
        <table>
          <thead>
            <tr><th>文件</th><th>Collection</th><th>状态</th><th>Chunks</th><th>入库时间</th></tr>
          </thead>
          <tbody id="documents"></tbody>
        </table>
      </section>
    </main>
    <script src="/static/admin.js"></script>
  </body>
</html>
```

- [ ] **Step 4: Implement admin JavaScript and CSS**

Create `admin.js` with:

```javascript
const jobs = new Map();

async function refreshDocuments() {
  const response = await fetch("/documents");
  const payload = await response.json();
  document.querySelector("#documents").innerHTML = payload.documents
    .map((doc) => `<tr><td>${doc.filename}</td><td>${doc.collection}</td><td>${doc.status}</td><td>${doc.chunk_count}</td><td>${doc.indexed_at ?? ""}</td></tr>`)
    .join("");
}

async function pollJob(jobId) {
  const response = await fetch(`/jobs/${jobId}`);
  const job = await response.json();
  jobs.set(jobId, job);
  renderJobs();
  if (job.status !== "succeeded" && job.status !== "failed") {
    window.setTimeout(() => pollJob(jobId), 1500);
  } else {
    refreshDocuments();
  }
}

function renderJobs() {
  document.querySelector("#jobs").innerHTML = Array.from(jobs.values())
    .map((job) => `<article><strong>${job.job_id}</strong> ${job.status} ${job.stage} ${job.progress}% <span>${job.error ?? ""}</span></article>`)
    .join("");
}

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const response = await fetch("/documents/upload", { method: "POST", body: formData });
  const payload = await response.json();
  document.querySelector("#upload-result").textContent = JSON.stringify(payload, null, 2);
  if (response.ok) {
    payload.jobs.forEach((job) => pollJob(job.job_id));
  }
});

document.querySelector("#refresh-documents").addEventListener("click", refreshDocuments);
refreshDocuments();
```

Create `admin.css`:

```css
:root {
  color: #17201a;
  background: #f4f1e8;
  font-family: "Aptos", "Microsoft YaHei", sans-serif;
}

body {
  margin: 0;
}

.shell {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  min-height: 100vh;
  padding: 24px;
}

.panel {
  background: #fffaf0;
  border: 1px solid #d8c9a8;
  border-radius: 18px;
  box-shadow: 0 16px 40px rgba(62, 48, 24, 0.1);
  padding: 18px;
}

#documents-panel {
  grid-column: 1 / -1;
}

form {
  display: grid;
  gap: 12px;
}

input,
button {
  border: 1px solid #b8a77e;
  border-radius: 10px;
  font: inherit;
  padding: 10px 12px;
}

button {
  background: #253b2f;
  color: #fffaf0;
  cursor: pointer;
}

table {
  border-collapse: collapse;
  width: 100%;
}

th,
td {
  border-bottom: 1px solid #e2d7bd;
  padding: 10px;
  text-align: left;
}

pre,
article {
  background: #f2ead8;
  border-radius: 12px;
  overflow: auto;
  padding: 12px;
}

@media (max-width: 900px) {
  .shell {
    grid-template-columns: 1fr;
    padding: 14px;
  }

  #documents-panel {
    grid-column: auto;
  }
}
```

- [ ] **Step 5: Verify admin tests pass**

Run: `cd rag-backend; python -m pytest tests/test_admin_page.py -v`

Expected: PASS.

- [ ] **Step 6: Commit admin page**

```bash
git add rag-backend/app/routers/admin.py rag-backend/app/templates rag-backend/app/static rag-backend/tests/test_admin_page.py
git commit -m "feat: add rag admin page"
```

## Task 10: Documentation and Full Verification

**Files:**
- Modify: `rag-backend/README.md`
- Test: full backend test suite

- [ ] **Step 1: Write README runbook**

Create `rag-backend/README.md` with:

````markdown
# RAG Backend

## Setup

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Environment

Copy `.env.example` to `.env` and set:

- `EMBEDDING_API_BASE_URL`
- `EMBEDDING_API_KEY` or `MINIMAX_API_KEY`
- `CHROMA_PERSIST_DIR`
- `REDIS_URL`

Secrets stay in `.env`; `.env` is not committed.

## Redis In WSL

```bash
sudo service redis-server start
redis-cli ping
```

If Windows cannot reach WSL Redis through `redis://localhost:6379/0`, run FastAPI and the RQ worker inside WSL.

## Run

```bash
uvicorn app.main:app --reload --port 8000
rq worker rag-ingestion --url redis://localhost:6379/0
```

Open `http://localhost:8000/admin`.

## Verify

```bash
python -m pytest -v
```
````

- [ ] **Step 2: Run complete Python test suite**

Run: `cd rag-backend; python -m pytest -v`

Expected: PASS.

- [ ] **Step 3: Run existing frontend tests to verify no regression**

Run: `npm run test:run`

Expected: PASS.

- [ ] **Step 4: Inspect git status**

Run: `git status --short`

Expected: only intended files under `rag-backend/`, root `.gitignore`, and docs are changed.

- [ ] **Step 5: Commit documentation and verification fixes**

```bash
git add rag-backend/README.md
git commit -m "docs: add rag backend runbook"
```

## Manual Verification Checklist

- [ ] Start Redis in WSL with `sudo service redis-server start`.
- [ ] Confirm Windows can reach Redis or run the backend stack inside WSL.
- [ ] Confirm `CHROMA_PERSIST_DIR` points to a writable directory.
- [ ] Start FastAPI with `uvicorn app.main:app --reload --port 8000`.
- [ ] Start RQ worker with `rq worker rag-ingestion --url redis://localhost:6379/0`.
- [ ] Open `http://localhost:8000/admin`.
- [ ] Upload one `.txt`, one `.md`, and one `.pdf`.
- [ ] Confirm each job moves from `queued` to `running` to `succeeded`.
- [ ] Confirm the Document area shows chunk counts.
- [ ] Restart FastAPI and confirm Chroma data persists.
- [ ] Use the existing LangGraph trace frontend against the same Chroma collection and confirm newly uploaded content appears in vector hits.

## Self-Review

- Spec coverage: This plan covers the independent FastAPI backend, `/admin` page with upload/job/document areas, `.txt`/`.md`/`.pdf` parsing, Redis/RQ retries, ChromaDB persistence, SQLite metadata, environment-variable secrets, default `500/50` chunking, chunk metadata, and no changes to the existing LangGraph frontend.
- Placeholder scan: The plan avoids unresolved placeholder markers, vague error handling, and generic test-writing steps without concrete expected behavior.
- Type consistency: `DocumentStatus`, `JobStatus`, `JobStage`, `DocumentRecord`, `JobRecord`, `TextChunk`, repository methods, queue methods, and service methods are introduced before later tasks use them.
