#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/rag-backend"
API_PORT="${API_PORT:-8000}"
ADMIN_URL="${ADMIN_URL:-http://localhost:${API_PORT}/admin}"
HEALTH_URL="${HEALTH_URL:-http://localhost:${API_PORT}/health}"
PYTHON_BIN="${PYTHON_BIN:-python}"
UVICORN_BIN="${UVICORN_BIN:-uvicorn}"
RQ_BIN="${RQ_BIN:-rq}"

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
  if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
    UVICORN_BIN="$BACKEND_DIR/.venv/bin/uvicorn"
    RQ_BIN="$BACKEND_DIR/.venv/bin/rq"
  elif [[ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ]]; then
    PYTHON_BIN="$BACKEND_DIR/.venv/Scripts/python.exe"
    UVICORN_BIN="$BACKEND_DIR/.venv/Scripts/uvicorn.exe"
    RQ_BIN="$BACKEND_DIR/.venv/Scripts/rq.exe"
  fi
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

  resolve_backend_commands
  require_command "$PYTHON_BIN"
  require_command "$UVICORN_BIN"
  require_command "$RQ_BIN"

  load_env
  start_redis

  cd "$BACKEND_DIR"

  mkdir -p "${UPLOAD_DIR:-./data/uploads}" "${CHROMA_PERSIST_DIR:-./data/chroma}" ./data

  echo "Starting FastAPI on port $API_PORT..."
  "$UVICORN_BIN" app.main:app --reload --port "$API_PORT" &
  API_PID="$!"

  echo "Starting RQ worker for queue ${RQ_QUEUE_NAME:-rag-ingestion}..."
  "$RQ_BIN" worker "${RQ_QUEUE_NAME:-rag-ingestion}" --url "${REDIS_URL:-redis://localhost:6379/0}" &
  WORKER_PID="$!"

  wait_for_health
  echo "Opening $ADMIN_URL"
  open_browser "$ADMIN_URL"

  echo "RAG backend is running. Press Ctrl+C to stop FastAPI and the worker."
  wait "$API_PID" "$WORKER_PID"
}

main "$@"
