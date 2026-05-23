from fastapi import FastAPI

from app.routers import collections, documents, health, ingestion_jobs


def create_app() -> FastAPI:
    app = FastAPI(title="RAG Backend Ingestion", version="0.1.0")
    app.include_router(documents.router)
    app.include_router(ingestion_jobs.router)
    app.include_router(collections.router)
    app.include_router(health.router)
    return app


app = create_app()
