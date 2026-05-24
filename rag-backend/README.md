# RAG Backend

FastAPI backend for local RAG document ingestion.

## Setup

From `rag-backend/`:

```powershell
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
- `RQ_QUEUE_NAME` if you change the default queue name

Secrets stay in `.env`; `.env` is not committed.

Make sure `CHROMA_PERSIST_DIR` points to a local directory that exists or can be created by the backend process, and that the process has permission to write there. The default local data directory is ignored by Git.

## Redis In WSL

```bash
sudo service redis-server start
redis-cli ping
```

If Windows cannot reach WSL Redis through `redis://localhost:6379/0`, run FastAPI and the RQ worker inside WSL.

## Run

Start FastAPI from `rag-backend/`:

```bash
uvicorn app.main:app --reload --port 8000
```

Start the RQ worker from `rag-backend/`. The worker's Redis URL and queue name must match the `REDIS_URL` and `RQ_QUEUE_NAME` values used by FastAPI, or uploads can enqueue jobs in one place while the worker listens somewhere else.

PowerShell does not automatically load `.env`, so set matching shell variables before starting the worker:

```powershell
$env:REDIS_URL = "redis://localhost:6379/0"
$env:RQ_QUEUE_NAME = "rag-ingestion"
rq worker $env:RQ_QUEUE_NAME --url $env:REDIS_URL
```

With the default `.env.example` values, this is equivalent to:

```powershell
rq worker rag-ingestion --url redis://localhost:6379/0
```

Open `http://localhost:8000/admin`.

## Verify

From `rag-backend/`:

```bash
python -m pytest -v
```
