# RAG Backend Ingestion Design

## Goal

Build an independent FastAPI RAG ingestion backend that lets the user upload `.txt`, `.md`, and `.pdf` files from a lightweight management page. The backend will parse files, split text into chunks, call the user's existing local Embedding API, and write the resulting vectors into a local persistent ChromaDB store.

The existing LangGraph trace debugging frontend remains the place for testing Agent behavior. It already displays node order, node status, timing, vector hits, final answers, request JSON, and response JSON. This backend only manages document ingestion into the same ChromaDB collection used by the existing RAG chain.

## Confirmed Scope

### In Scope

- Independent FastAPI backend project for RAG ingestion.
- FastAPI-rendered management page at `/admin`.
- Three management page areas:
  - Upload area for dragging files, choosing a collection, and showing `job_id`.
  - Job area for polling `/jobs/{job_id}` and displaying `queued`, `running`, `succeeded`, or `failed`.
  - Document area for viewing ingested documents, chunk counts, and collections.
- File support for `.txt`, `.md`, and `.pdf`.
- Redis + RQ background ingestion queue.
- Redis runs in WSL through `apt` installation, not Docker.
- ChromaDB local file persistence for the first version.
- SQLite metadata database for documents, ingestion jobs, and chunks.
- Local Embedding API adapter.
- API keys are injected through environment variables, not committed config files.
- Default text chunking uses `chunk_size=500` and `overlap=50`; both values remain configurable.
- Clean abstractions so the vector store can later switch from ChromaDB to Milvus.

### Out of Scope

- New retrieval test UI.
- New Agent answer UI.
- Changes to the existing LangGraph trace debugging frontend.
- Direct Milvus implementation in the first version.
- Authentication and multi-user permissions.
- Document deletion and vector deletion semantics.
- Production deployment, monitoring, billing, or cloud storage.

## Chosen Architecture

Use a layered FastAPI backend:

```text
API layer: routers/
  Handles HTTP requests, response shaping, file receiving, and parameter validation.
  It does not contain ingestion, parsing, embedding, or database business logic.

Service layer: services/
  Orchestrates business workflows such as upload -> create job -> parse -> chunk -> embed -> write vectors.
  It depends on interfaces, not concrete ChromaDB, Redis, or HTTP clients.

Infrastructure layer: infrastructure/
  Provides concrete adapters for Embedding API, ChromaDB, Redis/RQ, SQLite, parsers, and chunkers.
  Future Milvus support is added here behind the same VectorStore interface.
```

The dependency direction is one-way:

```text
routers -> services -> infrastructure protocols -> concrete adapters
workers -> services
```

The RQ worker does not implement ingestion logic directly. It receives a queued job and calls `IngestionService.ingest_document(document_id, collection)`.

## Project Structure

```text
rag-backend/
  app/
    main.py
    config.py
    dependencies.py

    routers/
      admin.py
      documents.py
      ingestion_jobs.py
      health.py
      collections.py

    services/
      document_service.py
      ingestion_service.py
      job_service.py

    infrastructure/
      embeddings/
        base.py
        local_api.py
      vectorstores/
        base.py
        chroma_store.py
        milvus_store.py
      parsers/
        base.py
        text_parser.py
        markdown_parser.py
        pdf_parser.py
        registry.py
      chunkers/
        base.py
        recursive.py
      queue/
        base.py
        rq_queue.py
      repositories/
        base.py
        sqlite.py

    workers/
      ingest_worker.py

  data/
    uploads/
    chroma/
    rag.sqlite

  tests/
```

`milvus_store.py` can be added as a later implementation file. The first version only wires `ChromaVectorStore`.

## API Contract

### `GET /admin`

Returns the lightweight management page.

The page includes:

- Upload area.
- Job status area.
- Document list area.

The page uses small native JavaScript helpers for upload, polling, and refreshing document data. It does not introduce React or another frontend framework.

### `GET /health`

Checks core dependencies.

Response shape:

```json
{
  "status": "ok",
  "checks": {
    "api": "ok",
    "redis": "ok",
    "chroma": "ok",
    "embedding_api": "ok",
    "sqlite": "ok"
  }
}
```

If a dependency is unavailable, `status` becomes `degraded` and the failing check includes a short message.

### `GET /collections`

Returns known ChromaDB collection names.

Response shape:

```json
{
  "collections": ["default", "docs"]
}
```

The upload page may allow selecting one of these names or typing a new collection name.

### `POST /documents/upload`

Accepts one or more files and creates one ingestion job per document.

Request:

```text
multipart/form-data
files: .txt/.md/.pdf, one or more
collection: string
```

Response:

```json
{
  "documents": [
    {
      "document_id": "doc_...",
      "filename": "example.pdf",
      "collection": "default"
    }
  ],
  "jobs": [
    {
      "job_id": "job_...",
      "document_id": "doc_...",
      "status": "queued"
    }
  ]
}
```

Validation:

- Reject unsupported extensions with `400`.
- Reject empty collection names with `400`.
- Reject files above `MAX_UPLOAD_MB` with `400`.
- If Redis/RQ is unavailable, return `503` and do not create a half-enqueued job.

### `GET /jobs/{job_id}`

Returns ingestion job status.

Response shape:

```json
{
  "job_id": "job_...",
  "document_id": "doc_...",
  "status": "running",
  "stage": "embedding",
  "progress": 65,
  "error": null,
  "created_at": "2026-05-24T10:00:00+08:00",
  "updated_at": "2026-05-24T10:00:04+08:00",
  "started_at": "2026-05-24T10:00:01+08:00",
  "finished_at": null
}
```

Allowed job statuses:

```text
queued | running | succeeded | failed
```

Allowed stages:

```text
uploaded | parsing | chunking | embedding | writing | done
```

### `GET /documents?collection=optional`

Returns uploaded and indexed documents.

Response shape:

```json
{
  "documents": [
    {
      "document_id": "doc_...",
      "filename": "example.pdf",
      "collection": "default",
      "status": "indexed",
      "chunk_count": 18,
      "source_path": "data/uploads/doc_.../original.pdf",
      "created_at": "2026-05-24T10:00:00+08:00",
      "indexed_at": "2026-05-24T10:00:08+08:00"
    }
  ]
}
```

Allowed document statuses:

```text
uploaded | indexing | indexed | failed
```

## Management Page Behavior

### Upload Area

- Drag or select multiple `.txt`, `.md`, or `.pdf` files.
- Choose or type a collection.
- Submit the upload.
- Show the returned `document_id` and `job_id` for each file.
- Add returned jobs to the polling list.

### Job Area

- Poll `/jobs/{job_id}` for recently created jobs.
- Display `status`, `stage`, `progress`, and `error`.
- Stop polling when a job reaches `succeeded` or `failed`.
- Refresh the document list after a job reaches a terminal status.

### Document Area

- Show filename, collection, status, chunk count, created time, and indexed time.
- Support filtering by collection.
- Do not provide deletion in the first version.

## Background Job Flow

```text
1. User uploads files from /admin.
2. documents router validates request shape and file constraints.
3. DocumentService saves each original file under data/uploads/{document_id}/.
4. DocumentService creates a document record with status uploaded.
5. JobService creates an ingestion job with status queued and stage uploaded.
6. QueueClient enqueues the job into RQ.
7. RQ worker receives the job and calls IngestionService.ingest_document.
8. IngestionService marks document indexing and job running.
9. ParserRegistry selects the parser by extension.
10. Parser extracts text and optionally saves extracted.txt.
11. Chunker splits text into chunks.
12. EmbeddingProvider calls the local Embedding API in batches.
13. ChromaVectorStore writes chunk texts, embeddings, ids, and metadata to ChromaDB.
14. Repository records chunk metadata and Chroma ids in SQLite.
15. JobService marks job succeeded and document indexed.
16. If a retryable step fails, RQ retries the job up to 3 times after the initial failed attempt.
17. If all retry attempts fail, the job and document are marked failed with the error message and the worker writes a structured log entry.
```

Progress mapping:

```text
uploaded: 5
parsing: 20
chunking: 35
embedding: 65
writing: 90
done: 100
```

Retry policy:

```text
max_retries: 3
max_attempts_including_initial_run: 4
retryable failures: parser IO errors, transient Embedding API errors, transient Chroma write errors
non-retryable failures: unsupported extension, empty parsed text, embedding dimension mismatch
final failure behavior: status=failed, document.status=failed, error saved to SQLite, structured log written
```

## Persistence Design

### Files

```text
data/
  uploads/
    {document_id}/
      original.ext
      extracted.txt
  chroma/
  rag.sqlite
```

`extracted.txt` is optional but useful for debugging parser output. If parsing fails, the document remains failed and the original file stays available for inspection.

### SQLite Tables

`documents`

```text
id
filename
collection
status
mime_type
file_size
source_path
text_path
content_hash
chunk_count
error
created_at
indexed_at
```

`ingestion_jobs`

```text
id
rq_job_id
document_id
collection
status
stage
progress
error
created_at
updated_at
started_at
finished_at
```

`chunks`

```text
id
document_id
collection
chunk_index
chroma_id
content_preview
token_count
source_file
upload_time
created_at
```

### ChromaDB IDs and Metadata

Stable Chroma ids:

```text
{document_id}:{chunk_index}
```

Chroma metadata:

```json
{
  "document_id": "doc_...",
  "filename": "example.pdf",
  "source_file": "example.pdf",
  "collection": "default",
  "chunk_index": 0,
  "upload_time": "2026-05-24T10:00:00+08:00",
  "source": "upload",
  "content_hash": "sha256..."
}
```

Chroma stores the full chunk text in `documents`. SQLite stores only a preview and management metadata.

## Infrastructure Interfaces

### Embedding Provider

```python
class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...
```

First implementation:

```python
class LocalApiEmbeddingProvider:
    ...
```

This adapter calls the user's existing local Embedding API. It supports providers exposed by that local API, including MiniMax `embo-01` when configured. API keys are injected through environment variables such as `EMBEDDING_API_KEY` or provider-specific variables like `MINIMAX_API_KEY`; committed config files must not contain secrets.

### Vector Store

```python
class VectorStore(Protocol):
    def ensure_collection(self, name: str) -> None:
        ...

    def add_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        ...
```

First implementation:

```python
class ChromaVectorStore:
    ...
```

Future implementation:

```python
class MilvusVectorStore:
    ...
```

The service layer only depends on `VectorStore`, so switching to Milvus later should not require changing routers or ingestion orchestration.

### Queue Client

```python
class QueueClient(Protocol):
    def enqueue_ingestion(self, document_id: str, collection: str) -> str:
        ...
```

First implementation:

```python
class RqQueueClient:
    ...
```

### Parser and Chunker

```python
class DocumentParser(Protocol):
    def parse(self, path: Path) -> str:
        ...
```

Implementations:

```text
TextParser
MarkdownParser
PdfParser
ParserRegistry
```

```python
class Chunker(Protocol):
    def split(self, text: str) -> list[TextChunk]:
        ...
```

First implementation:

```python
class RecursiveTextChunker:
    ...
```

## ChromaDB Sharing With Existing RAG Chain

The existing Agent/RAG backend must use the same:

```text
CHROMA_PERSIST_DIR
collection name
embedding model
embedding dimension
```

The current frontend's `vectorProvider: "qdrant"` value is only a stale display label. It does not describe the real backend. This ingestion backend should use ChromaDB as the first vector store implementation.

## Configuration

```env
APP_ENV=local
DATABASE_URL=sqlite:///./data/rag.sqlite

UPLOAD_DIR=./data/uploads
CHROMA_PERSIST_DIR=./data/chroma

REDIS_URL=redis://localhost:6379/0
RQ_QUEUE_NAME=rag-ingestion

EMBEDDING_API_BASE_URL=http://localhost:xxxx
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

Operational notes:

- Redis is installed and started inside WSL through `apt`.
- Windows must be able to reach Redis through the configured `REDIS_URL`, or the full FastAPI/RQ stack should run inside WSL.
- `CHROMA_PERSIST_DIR` must point to a writable directory.
- Embedding API keys are provided by environment variables only. `.env.example` may list variable names but must leave secret values empty.
- If the existing RAG chain runs in a different environment, both processes must resolve `CHROMA_PERSIST_DIR` to the same physical storage location.

## Error Handling

Request-time errors:

- Unsupported file extension returns `400`.
- Empty collection returns `400`.
- Upload above `MAX_UPLOAD_MB` returns `400`.
- Redis/RQ unavailable returns `503`.
- Chroma persistence directory unavailable or not writable returns `503` from `/health`.

Worker-time errors:

- Retryable parser IO failures retry up to 3 times after the initial failed attempt, then mark job failed and document failed.
- Empty parsed text is non-retryable and immediately marks job failed and document failed.
- Retryable Embedding API failures retry up to 3 times after the initial failed attempt, then mark job failed and document failed.
- Embedding dimension mismatch is non-retryable and immediately marks job failed and document failed.
- Retryable Chroma write failures retry up to 3 times after the initial failed attempt, then mark job failed and document failed.

All worker-time failures are saved to:

```text
ingestion_jobs.error
documents.error
```

The worker also writes structured logs for failed attempts and final failures. The management page displays the latest persisted job error in the Job area.

## Local Runbook

Start Redis in WSL:

```bash
sudo service redis-server start
```

Start FastAPI:

```bash
uvicorn app.main:app --reload --port 8000
```

Start the RQ worker:

```bash
rq worker rag-ingestion --url redis://localhost:6379/0
```

Open the management page:

```text
http://localhost:8000/admin
```

The existing LangGraph trace debugging frontend continues to run separately and validates that the Agent can retrieve newly ingested ChromaDB content.

## Testing Strategy

### Unit Tests

- Text parser extracts `.txt` content.
- Markdown parser extracts `.md` content.
- PDF parser extracts readable `.pdf` text.
- Chunker respects `CHUNK_SIZE` and `CHUNK_OVERLAP`.
- Chunker defaults to `CHUNK_SIZE=500` and `CHUNK_OVERLAP=50` when no override is provided.
- Local Embedding API adapter sends the expected request, reads API keys from environment variables, and validates response dimensions.
- Chroma vector store writes chunks, ids, embeddings, and metadata to a temporary persistent directory.
- Job service transitions jobs through queued, running, succeeded, and failed.
- Document service saves uploaded files and enqueues jobs through a fake queue client.
- Ingestion service orchestrates parser, chunker, embedder, vector store, and repository fakes in the correct order.

### Integration Tests

- `POST /documents/upload` creates document records and job records.
- `GET /jobs/{job_id}` returns the expected job state.
- `GET /documents` returns documents with chunk counts.
- A worker execution indexes a fixture document into ChromaDB and records chunks in SQLite.
- Failure in parser, embedding, or Chroma write updates job and document status to failed.
- Retryable worker failures retry up to 3 times after the initial failed attempt before final failed status is persisted.
- Chroma metadata includes `source_file`, `chunk_index`, and `upload_time`.

### Manual Verification

- Upload one `.txt`, one `.md`, and one `.pdf`.
- Confirm jobs move from `queued` to `running` to `succeeded`.
- Confirm the Document area shows correct `chunk_count`.
- Confirm `data/chroma` is written and remains available after backend restart.
- Confirm the existing LangGraph frontend Agent can retrieve the uploaded content from the same ChromaDB collection.
- Confirm Redis connectivity from Windows to WSL, or run FastAPI and RQ inside WSL if cross-environment access is unreliable.
- Confirm `CHROMA_PERSIST_DIR` is writable from the process that runs FastAPI and the process that runs the existing RAG chain.

## Implementation Guidance

- Keep routers thin.
- Keep service methods small and focused on orchestration.
- Keep concrete dependencies inside infrastructure adapters.
- Treat ChromaDB as the first `VectorStore` implementation, not as a service-layer concept.
- Do not add retrieval test UI in the management page.
- Do not add Agent answer UI in the management page.
- Do not modify the existing LangGraph trace debugging frontend for this feature.
- Preserve the option to add Milvus later by implementing the existing `VectorStore` protocol.
