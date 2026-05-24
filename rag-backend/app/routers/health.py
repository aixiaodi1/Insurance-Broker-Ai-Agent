from collections.abc import Callable

from fastapi import APIRouter, Request

from app.dependencies import get_embedder, get_queue_client, get_repository, get_vector_store
from app.infrastructure.embeddings.base import EmbeddingProvider
from app.infrastructure.queue.base import QueueClient


router = APIRouter(tags=["health"])


def _run_check(check: Callable[[], object]) -> dict:
    try:
        check()
    except Exception:
        return {"status": "error", "error": "check_failed"}
    return {"status": "ok"}


def _resolve(request: Request, dependency: Callable[[], object]) -> object:
    provider = request.app.dependency_overrides.get(dependency, dependency)
    return provider()


def _check_redis(queue_client: QueueClient) -> None:
    if hasattr(queue_client, "ping"):
        queue_client.ping()
        return

    redis_client = getattr(queue_client, "redis", None)
    if redis_client is not None and hasattr(redis_client, "ping"):
        redis_client.ping()


def _check_embedding_provider(embedder: EmbeddingProvider) -> None:
    health_check = getattr(embedder, "health_check", None)
    if callable(health_check):
        health_check()
        return

    if not callable(getattr(embedder, "embed_texts", None)):
        raise RuntimeError("embedding provider unavailable")


@router.get("/health")
def health(request: Request) -> dict:
    checks = {
        "api": {"status": "ok"},
        "redis": _run_check(lambda: _check_redis(_resolve(request, get_queue_client))),
        "chroma": _run_check(lambda: _resolve(request, get_vector_store).list_collections()),
        "embedding_api": _run_check(lambda: _check_embedding_provider(_resolve(request, get_embedder))),
        "sqlite": _run_check(lambda: _resolve(request, get_repository).initialize()),
    }
    overall_status = "ok" if all(check["status"] == "ok" for check in checks.values()) else "degraded"
    return {"status": overall_status, "checks": checks}
