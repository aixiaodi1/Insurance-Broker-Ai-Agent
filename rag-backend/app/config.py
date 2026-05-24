from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = "local"
    database_url: str = "sqlite:///./data/rag.sqlite"
    upload_dir: Path = Path("./data/uploads")
    chroma_persist_dir: Path = Path("./data/chroma")
    redis_url: str = "redis://localhost:6379/0"
    rq_queue_name: str = "rag-ingestion"
    embedding_api_base_url: str = "http://localhost:9000"
    embedding_api_path: str = "/v1/embeddings"
    embedding_api_key: str = ""
    minimax_api_key: str = ""
    embedding_model: str = "embo-01"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 32
    chunk_size: int = 500
    chunk_overlap: int = 50
    max_upload_mb: int = 50
    max_upload_batch_mb: int = 100
    allowed_extensions_raw: str = Field(default=".txt,.md,.pdf", alias="ALLOWED_EXTENSIONS")

    @model_validator(mode="before")
    @classmethod
    def support_allowed_extensions_constructor_arg(cls, data: object) -> object:
        if not isinstance(data, dict) or "allowed_extensions" not in data:
            return data

        value = data["allowed_extensions"]
        if isinstance(value, list):
            value = ",".join(str(item) for item in value)

        return {**data, "allowed_extensions_raw": value}

    @property
    def allowed_extensions(self) -> list[str]:
        return [
            item.strip().lower()
            for item in self.allowed_extensions_raw.split(",")
            if item.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
