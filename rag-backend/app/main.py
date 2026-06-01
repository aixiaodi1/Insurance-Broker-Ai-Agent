from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE

from app.dependencies import close_cached_dependencies, set_app_state
from app.infrastructure.repositories.sqlite import SQLiteRepository
from app.observability import configure_logging
from app.retrieval.bm25_indexer import MemoryBM25Indexer
from app.routers import admin, agent, collections, documents, health, ingestion_jobs

configure_logging()

STATIC_DIR = Path(__file__).resolve().parent / "static"

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    state: dict = {}

    from app.config import Settings

    settings = Settings()

    def _is_model_cached(repo_id: str) -> bool:
        cache_key = f"models--{repo_id.replace('/', '--')}"
        cache_path = Path(HUGGINGFACE_HUB_CACHE) / cache_key
        return cache_path.is_dir() and any(cache_path.rglob("model.safetensors")) or any(cache_path.rglob("pytorch_model.bin"))

    if _is_model_cached(settings.embedding_model):
        try:
            from sentence_transformers import SentenceTransformer

            print("[lifespan] Loading embedding model...")
            state["embedding_model"] = SentenceTransformer(
                settings.embedding_model, local_files_only=True
            )
        except Exception as exc:
            print(f"[lifespan] Embedding model loading failed: {exc}")
    else:
        print(f"[lifespan] Embedding model not cached, skipping")

    if _is_model_cached(settings.cross_encoder_model):
        try:
            from sentence_transformers import CrossEncoder

            print("[lifespan] Loading cross-encoder model...")
            state["cross_encoder"] = CrossEncoder(
                settings.cross_encoder_model, local_files_only=True
            )
        except Exception as exc:
            print(f"[lifespan] Cross-encoder model loading failed: {exc}")
    else:
        print(f"[lifespan] Cross-encoder model not cached, skipping")

    try:
        repo = SQLiteRepository(settings.database_url)
        repo.initialize()
        all_chunks = repo.list_all_child_texts()
        print(f"[lifespan] Loading {len(all_chunks)} child chunks into BM25...")
        bm25 = MemoryBM25Indexer()
        if all_chunks:
            bm25.rebuild(all_chunks)
        state["bm25_indexer"] = bm25
    except Exception as exc:
        print(f"[lifespan] BM25 index loading skipped: {exc}")

    set_app_state(state)
    try:
        yield
    finally:
        close_cached_dependencies()


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Backend Ingestion", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(admin.router)
    app.include_router(agent.router)
    app.include_router(documents.router)
    app.include_router(ingestion_jobs.router)
    app.include_router(collections.router)
    app.include_router(health.router)
    return app


app = create_app()
