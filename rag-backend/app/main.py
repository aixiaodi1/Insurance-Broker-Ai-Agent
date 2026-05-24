from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.dependencies import close_cached_dependencies
from app.routers import admin, collections, documents, health, ingestion_jobs


STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        close_cached_dependencies()


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Backend Ingestion", version="0.1.0", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(admin.router)
    app.include_router(documents.router)
    app.include_router(ingestion_jobs.router)
    app.include_router(collections.router)
    app.include_router(health.router)
    return app


app = create_app()
