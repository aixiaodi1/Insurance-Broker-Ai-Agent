from pathlib import Path

from app.config import Settings


def test_settings_defaults_are_local_and_safe(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'rag.sqlite'}",
        upload_dir=tmp_path / "uploads",
        chroma_persist_dir=tmp_path / "chroma",
        embedding_api_base_url="http://localhost:9000",
    )

    assert settings.app_env == "local"
    assert settings.chunk_size == 500
    assert settings.chunk_overlap == 50
    assert settings.embedding_model == "embo-01"
    assert settings.embedding_api_key == ""
    assert settings.minimax_api_key == ""
    assert settings.allowed_extensions == [".txt", ".md", ".pdf"]
