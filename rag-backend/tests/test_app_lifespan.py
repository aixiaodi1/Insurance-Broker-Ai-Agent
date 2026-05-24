from pathlib import Path

from fastapi.testclient import TestClient

from app import dependencies
from app.config import Settings
from app.main import create_app


class FakeVectorStore:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_app_shutdown_closes_cached_vector_store(monkeypatch, tmp_path: Path) -> None:
    store = FakeVectorStore()
    dependencies.get_vector_store.cache_clear()
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: Settings(
            database_url=f"sqlite:///{tmp_path / 'rag.sqlite'}",
            upload_dir=tmp_path / "uploads",
            chroma_persist_dir=tmp_path / "chroma",
            embedding_api_base_url="http://localhost:9000",
        ),
    )
    monkeypatch.setattr(dependencies, "ChromaVectorStore", lambda persist_dir: store)

    assert dependencies.get_vector_store() is store

    with TestClient(create_app()):
        pass

    assert store.close_calls == 1
