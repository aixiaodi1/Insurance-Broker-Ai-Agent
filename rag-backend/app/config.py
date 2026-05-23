from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
    allowed_extensions: list[str] = Field(default_factory=lambda: [".txt", ".md", ".pdf"])

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def parse_extensions(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
