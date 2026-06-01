# RAG Backend

FastAPI backend for local RAG document ingestion.

## Setup

From `rag-backend/`:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Local SentenceTransformers embeddings are optional because they can pull large
Torch/model dependencies. If the selected Python environment does not already
have them, either reuse your existing RAG environment with `RAG_PYTHON` or
install them explicitly:

```bash
python -m pip install -e ".[local-embeddings]"
```

## Environment

Copy `.env.example` to `.env` and set:

- `EMBEDDING_API_BASE_URL`
- `EMBEDDING_MODEL`
- `CHROMA_PERSIST_DIR`
- `REDIS_URL`
- `RQ_QUEUE_NAME` if you change the default queue name

Secrets stay in `.env`; `.env` is not committed.

The default embedding mode calls the local model API:

```env
EMBEDDING_PROVIDER=api
LOCAL_MODEL_API_BASE_URL=http://localhost:9000
EMBEDDING_API_BASE_URL=http://localhost:9000
EMBEDDING_API_PATH=/v1/embeddings
EMBEDDING_MODEL=shibing624/text2vec-base-chinese
RERANK_API_BASE_URL=http://localhost:9000
RERANK_API_PATH=/v1/rerank
RERANK_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
```

`start.bat` starts this local model API on port `9000`. It exposes:

- `POST /v1/embeddings` for `shibing624/text2vec-base-chinese`
- `POST /v1/rerank` for `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`

To run embeddings inside the ingestion worker instead of using the HTTP model API, set:

```env
EMBEDDING_PROVIDER=sentence-transformers
```

Make sure `CHROMA_PERSIST_DIR` points to a local directory that exists or can be created by the backend process, and that the process has permission to write there. The default local data directory is ignored by Git.

## Redis In WSL

```bash
sudo service redis-server start
redis-cli ping
```

If Windows cannot reach WSL Redis through `redis://localhost:6379/0`, run FastAPI and the RQ worker inside WSL.

## Run

### One-Command Start

From the repository root, run:

```bash
./start.sh
```

On Windows, you can double-click `start-wsl.bat` from the repository root. It opens WSL, automatically changes to this project directory, runs `./start.sh`, and keeps the window open if startup fails so you can read the error.

If your local embedding model already lives in a Windows virtual environment,
double-click `start.bat` instead. It starts Redis through WSL, then runs FastAPI,
the local model API, the RQ worker, and the Next.js frontend with Windows Python/Node.

The script will:

- start Redis with `sudo service redis-server start` when Redis is not already running
- load `rag-backend/.env`
- use `rag-backend/.venv` automatically when it exists
- reuse another RAG Python environment when `RAG_PYTHON` is set
- install missing backend Python packages into the selected Python environment when needed
- check local embedding packages without auto-installing heavy Torch/model dependencies
- start FastAPI on `http://localhost:8000`
- start the RQ worker with the configured `RQ_QUEUE_NAME` and `REDIS_URL`
- open `http://localhost:8000/admin` in your browser

Press `Ctrl+C` in the script terminal to stop FastAPI and the worker.

If `rag-backend/.env` does not exist yet, create it first:

```bash
cp rag-backend/.env.example rag-backend/.env
```

You can override the defaults when starting:

```bash
API_PORT=8010 ./start.sh
```

If you want the script to report missing dependencies without installing them automatically:

```bash
AUTO_INSTALL_DEPS=0 ./start.sh
```

To reuse an existing RAG virtual environment instead of installing packages again, point `RAG_PYTHON` at that environment's Python:

```bash
RAG_PYTHON="/mnt/f/Dev/Hermes/src/hermes-agent/venv/Scripts/python.exe" ./start.sh
```

For one-click startup, put the same value in `rag-backend/.env`:

```env
RAG_PYTHON=/mnt/f/Dev/Hermes/src/hermes-agent/venv/Scripts/python.exe
```

For `start.bat` on Windows, use a Windows path:

```env
RAG_PYTHON_WINDOWS=E:\RAG\.venv\Scripts\python.exe
```

On Windows PowerShell, run the same script through WSL/Git Bash and convert the Windows path to a shell-readable path, for example `F:\Dev\Hermes\...` becomes `/mnt/f/Dev/Hermes/...` in WSL.

If you really want `start.sh` to install the optional local embedding runtime,
opt in explicitly:

```bash
AUTO_INSTALL_LOCAL_EMBEDDINGS=1 ./start.sh
```

This can download large Torch/model packages, so reusing your existing RAG
environment is usually safer.

### Manual Start

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
