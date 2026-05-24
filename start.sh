#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/rag-backend"
API_PORT="${API_PORT:-8000}"
ADMIN_URL="${ADMIN_URL:-http://localhost:${API_PORT}/admin}"
HEALTH_URL="${HEALTH_URL:-http://localhost:${API_PORT}/health}"
PYTHON_BIN="${RAG_PYTHON:-${PYTHON_BIN:-python}}"
AUTO_INSTALL_DEPS="${AUTO_INSTALL_DEPS:-1}"
AUTO_INSTALL_LOCAL_EMBEDDINGS="${AUTO_INSTALL_LOCAL_EMBEDDINGS:-0}"

API_PID=""
WORKER_PID=""

cleanup() {
  if [[ -n "$API_PID" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
  fi
  if [[ -n "$WORKER_PID" ]] && kill -0 "$WORKER_PID" 2>/dev/null; then
    kill "$WORKER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

resolve_backend_commands() {
  if [[ -n "${RAG_PYTHON:-}" ]]; then
    PYTHON_BIN="$RAG_PYTHON"
  elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
  elif [[ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ]]; then
    PYTHON_BIN="$BACKEND_DIR/.venv/Scripts/python.exe"
  fi
}

verify_python_dependencies() {
  "$PYTHON_BIN" - <<'PY'
import importlib.util
import sys

modules = {
    "chromadb": "chromadb",
    "fastapi": "fastapi",
    "httpx": "httpx",
    "jinja2": "jinja2",
    "pydantic-settings": "pydantic_settings",
    "pypdf": "pypdf",
    "python-multipart": "multipart",
    "redis": "redis",
    "rq": "rq",
    "uvicorn": "uvicorn",
}
missing = [package for package, module in modules.items() if importlib.util.find_spec(module) is None]
if missing:
    print("Missing Python packages in:", sys.executable)
    for package in missing:
        print(f"  - {package}")
    raise SystemExit(1)
print("Using Python:", sys.executable)
PY
}

verify_local_embedding_dependencies() {
  "$PYTHON_BIN" - <<'PY'
import importlib.util
import os
import sys

provider = os.getenv("EMBEDDING_PROVIDER", "sentence-transformers").lower()
if provider not in {"sentence-transformers", "local", "local-model"}:
    raise SystemExit(0)

modules = {
    "sentence-transformers": "sentence_transformers",
}
missing = [package for package, module in modules.items() if importlib.util.find_spec(module) is None]
if missing:
    print("Missing local embedding packages in:", sys.executable, file=sys.stderr)
    for package in missing:
        print(f"  - {package}", file=sys.stderr)
    print("These packages can pull large torch/model dependencies, so start.sh will not auto-install them.", file=sys.stderr)
    print('Reuse your existing RAG environment with:', file=sys.stderr)
    print('  RAG_PYTHON=/path/to/venv/bin/python ./start.sh', file=sys.stderr)
    print('Or install the optional local embedding runtime manually with:', file=sys.stderr)
    print('  cd rag-backend && python -m pip install -e ".[local-embeddings]"', file=sys.stderr)
    print('Fallback option: set EMBEDDING_PROVIDER=api and EMBEDDING_API_BASE_URL=http://...', file=sys.stderr)
    raise SystemExit(1)
PY
}

ensure_local_embedding_dependencies() {
  if verify_local_embedding_dependencies; then
    return
  fi

  if [[ "$AUTO_INSTALL_LOCAL_EMBEDDINGS" != "1" ]]; then
    exit 1
  fi

  echo "Installing optional local embedding dependencies into: $PYTHON_BIN"
  echo "This may download large torch/model packages. Press Ctrl+C now to cancel."
  sleep 5
  (
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[local-embeddings]"
  )

  verify_local_embedding_dependencies
}

ensure_python_dependencies() {
  if verify_python_dependencies; then
    return
  fi

  if [[ "$AUTO_INSTALL_DEPS" != "1" ]]; then
    echo 'Install them with: python -m pip install -e "rag-backend[dev]"' >&2
    echo "Or reuse another RAG environment:" >&2
    echo "  RAG_PYTHON=/path/to/venv/bin/python ./start.sh" >&2
    exit 1
  fi

  echo "Installing missing backend dependencies into: $PYTHON_BIN"
  (
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
  )

  verify_python_dependencies
}

load_env() {
  local env_file="$BACKEND_DIR/.env"
  if [[ ! -f "$env_file" ]]; then
    echo "Missing $env_file" >&2
    echo "Create it first, for example:" >&2
    echo "  cp rag-backend/.env.example rag-backend/.env" >&2
    exit 1
  fi

  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
}

start_redis() {
  if command -v redis-cli >/dev/null 2>&1 && redis-cli ping >/dev/null 2>&1; then
    echo "Redis is already running."
    return
  fi

  if command -v service >/dev/null 2>&1; then
    echo "Starting Redis with service..."
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      service redis-server start
    elif command -v sudo >/dev/null 2>&1; then
      sudo service redis-server start
    else
      echo "sudo is unavailable; please start Redis manually." >&2
      exit 1
    fi
  else
    echo "The service command is unavailable; please start Redis manually." >&2
    exit 1
  fi

  if command -v redis-cli >/dev/null 2>&1; then
    redis-cli ping >/dev/null
  fi
}

open_browser() {
  local url="$1"
  if command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c start "" "$url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 || true
  else
    echo "Open this URL manually: $url"
  fi
}

wait_for_health() {
  echo "Waiting for FastAPI health check..."
  for _ in {1..40}; do
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
        return
      fi
    elif command -v python >/dev/null 2>&1; then
      if python - "$HEALTH_URL" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import urlopen

urlopen(sys.argv[1], timeout=2).read()
PY
      then
        return
      fi
    fi
    sleep 0.5
  done

  echo "FastAPI did not respond at $HEALTH_URL in time." >&2
  exit 1
}

main() {
  if [[ ! -d "$BACKEND_DIR" ]]; then
    echo "Cannot find backend directory: $BACKEND_DIR" >&2
    exit 1
  fi

  load_env
  resolve_backend_commands
  require_command "$PYTHON_BIN"
  ensure_python_dependencies

  ensure_local_embedding_dependencies
  start_redis

  cd "$BACKEND_DIR"

  mkdir -p "${UPLOAD_DIR:-./data/uploads}" "${CHROMA_PERSIST_DIR:-./data/chroma}" ./data

  echo "Starting FastAPI on port $API_PORT..."
  "$PYTHON_BIN" -m uvicorn app.main:app --reload --port "$API_PORT" &
  API_PID="$!"

  echo "Starting RQ worker for queue ${RQ_QUEUE_NAME:-rag-ingestion}..."
  "$PYTHON_BIN" -m rq.cli worker "${RQ_QUEUE_NAME:-rag-ingestion}" --url "${REDIS_URL:-redis://localhost:6379/0}" &
  WORKER_PID="$!"

  sleep 1
  if ! kill -0 "$WORKER_PID" 2>/dev/null; then
    echo "RQ worker exited during startup. Check the terminal output above for the Python/RQ error." >&2
    exit 1
  fi

  wait_for_health
  echo "Opening $ADMIN_URL"
  open_browser "$ADMIN_URL"

  echo "RAG backend is running. Press Ctrl+C to stop FastAPI and the worker."
  wait "$API_PID" "$WORKER_PID"
}

main "$@"
