import sqlite3
from pathlib import Path

import pytest

from app.domain import DocumentStatus, JobStage, JobStatus
from app.infrastructure.repositories import sqlite as sqlite_repository
from app.infrastructure.repositories.sqlite import SQLiteRepository


def test_repository_creates_document_job_and_chunks(tmp_path: Path) -> None:
    repo = SQLiteRepository(f"sqlite:///{tmp_path / 'rag.sqlite'}")
    repo.initialize()

    document = repo.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=12,
        source_path=str(tmp_path / "guide.md"),
        content_hash="abc123",
    )
    job = repo.create_job(document_id=document.id, collection="docs")

    repo.mark_document_indexing(document.id)
    repo.update_job(job.id, status=JobStatus.RUNNING, stage=JobStage.EMBEDDING, progress=65)
    repo.replace_chunks(
        document_id=document.id,
        collection="docs",
        chunks=[
            {
                "chunk_index": 0,
                "chroma_id": f"{document.id}:0",
                "content_preview": "hello",
                "token_count": 1,
                "source_file": "guide.md",
                "upload_time": document.created_at,
            }
        ],
    )
    repo.mark_document_indexed(document.id, chunk_count=1)
    repo.update_job(job.id, status=JobStatus.SUCCEEDED, stage=JobStage.DONE, progress=100)

    stored_document = repo.get_document(document.id)
    stored_job = repo.get_job(job.id)

    assert stored_document.status == DocumentStatus.INDEXED
    assert stored_document.chunk_count == 1
    assert stored_job.status == JobStatus.SUCCEEDED
    assert repo.list_documents(collection="docs")[0].filename == "guide.md"


def test_repository_replace_chunks_removes_stale_document_chunks(tmp_path: Path) -> None:
    database_path = tmp_path / "rag.sqlite"
    repo = SQLiteRepository(f"sqlite:///{database_path}")
    repo.initialize()
    document = repo.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=12,
        source_path=str(tmp_path / "guide.md"),
        content_hash="abc123",
    )
    other_document = repo.create_document(
        filename="other.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=10,
        source_path=str(tmp_path / "other.md"),
        content_hash="def456",
    )

    repo.replace_chunks(
        document_id=document.id,
        collection="docs",
        chunks=[
            {
                "chunk_index": 0,
                "chroma_id": f"{document.id}:0",
                "content_preview": "stale first",
                "token_count": 2,
                "source_file": "guide.md",
                "upload_time": document.created_at,
            },
            {
                "chunk_index": 1,
                "chroma_id": f"{document.id}:1",
                "content_preview": "stale second",
                "token_count": 2,
                "source_file": "guide.md",
                "upload_time": document.created_at,
            },
        ],
    )
    repo.replace_chunks(
        document_id=other_document.id,
        collection="docs",
        chunks=[
            {
                "chunk_index": 0,
                "chroma_id": f"{other_document.id}:0",
                "content_preview": "other",
                "token_count": 1,
                "source_file": "other.md",
                "upload_time": other_document.created_at,
            }
        ],
    )

    repo.replace_chunks(
        document_id=document.id,
        collection="docs",
        chunks=[
            {
                "chunk_index": 0,
                "chroma_id": f"{document.id}:0",
                "content_preview": "fresh only",
                "token_count": 2,
                "source_file": "guide.md",
                "upload_time": document.created_at,
            }
        ],
    )

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT document_id, chunk_index, chroma_id, content_preview
            FROM chunks
            ORDER BY document_id, chunk_index
            """
        ).fetchall()

    assert set(rows) == {
        (document.id, 0, f"{document.id}:0", "fresh only"),
        (other_document.id, 0, f"{other_document.id}:0", "other"),
    }


def test_repository_replace_chunks_rolls_back_delete_when_insert_fails(tmp_path: Path) -> None:
    database_path = tmp_path / "rag.sqlite"
    repo = SQLiteRepository(f"sqlite:///{database_path}")
    repo.initialize()
    document = repo.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=12,
        source_path=str(tmp_path / "guide.md"),
        content_hash="abc123",
    )
    repo.replace_chunks(
        document_id=document.id,
        collection="docs",
        chunks=[
            {
                "chunk_index": 0,
                "chroma_id": f"{document.id}:0",
                "content_preview": "original",
                "token_count": 1,
                "source_file": "guide.md",
                "upload_time": document.created_at,
            }
        ],
    )

    with pytest.raises(sqlite3.IntegrityError):
        repo.replace_chunks(
            document_id=document.id,
            collection="docs",
            chunks=[
                {
                    "chunk_index": 0,
                    "chroma_id": f"{document.id}:0",
                    "content_preview": None,
                    "token_count": 1,
                    "source_file": "guide.md",
                    "upload_time": document.created_at,
                }
            ],
        )

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT chroma_id, content_preview FROM chunks WHERE document_id = ?",
            (document.id,),
        ).fetchall()

    assert rows == [(f"{document.id}:0", "original")]


def test_repository_preserves_finished_at_after_terminal_update(
    tmp_path: Path,
    monkeypatch,
) -> None:
    timestamps = iter(
        [
            "2026-05-24T01:00:00+08:00",
            "2026-05-24T01:00:01+08:00",
            "2026-05-24T01:00:02+08:00",
            "2026-05-24T01:00:03+08:00",
            "2026-05-24T01:00:04+08:00",
        ]
    )
    monkeypatch.setattr(SQLiteRepository, "_now", staticmethod(lambda: next(timestamps)))

    repo = SQLiteRepository(f"sqlite:///{tmp_path / 'rag.sqlite'}")
    repo.initialize()
    document = repo.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=12,
        source_path=str(tmp_path / "guide.md"),
        content_hash="abc123",
    )
    job = repo.create_job(document_id=document.id, collection="docs")

    repo.update_job(job.id, status=JobStatus.SUCCEEDED, stage=JobStage.DONE, progress=100)
    first_finished_at = repo.get_job(job.id).finished_at

    repo.update_job(job.id, status=JobStatus.SUCCEEDED, stage=JobStage.DONE, progress=100)

    assert repo.get_job(job.id).finished_at == first_finished_at


def test_repository_gets_job_by_rq_id(tmp_path: Path) -> None:
    repo = SQLiteRepository(f"sqlite:///{tmp_path / 'rag.sqlite'}")
    repo.initialize()
    document = repo.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=12,
        source_path=str(tmp_path / "guide.md"),
        content_hash="abc123",
    )
    job = repo.create_job(document_id=document.id, collection="docs")

    repo.set_job_rq_id(job.id, "rq-job-123")

    assert repo.get_job_by_rq_id("rq-job-123").id == job.id


def test_repository_updates_document_source_path(tmp_path: Path) -> None:
    repo = SQLiteRepository(f"sqlite:///{tmp_path / 'rag.sqlite'}")
    repo.initialize()
    document = repo.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=12,
        source_path=str(tmp_path / "_pending" / "guide.md"),
        content_hash="abc123",
    )
    final_path = str(tmp_path / document.id / "original.md")

    updated = repo.update_document_source_path(document.id, final_path)

    assert updated.source_path == final_path
    assert repo.get_document(document.id).source_path == final_path


def test_repository_closes_connections_after_operations(tmp_path: Path, monkeypatch) -> None:
    closed_paths: list[Path] = []
    real_connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        def close(self) -> None:
            closed_paths.append(Path(self.execute("PRAGMA database_list").fetchone()[2]))
            super().close()

    def connect(*args, **kwargs):
        kwargs["factory"] = TrackedConnection
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite_repository.sqlite3, "connect", connect)

    database_path = tmp_path / "rag.sqlite"
    repo = SQLiteRepository(f"sqlite:///{database_path}")
    repo.initialize()
    document = repo.create_document(
        filename="guide.md",
        collection="docs",
        mime_type="text/markdown",
        file_size=12,
        source_path=str(tmp_path / "guide.md"),
        content_hash="abc123",
    )
    job = repo.create_job(document_id=document.id, collection="docs")
    repo.update_job(job.id, status=JobStatus.SUCCEEDED, stage=JobStage.DONE, progress=100)

    renamed_path = tmp_path / "rag-renamed.sqlite"
    database_path.rename(renamed_path)
    renamed_path.unlink()

    assert closed_paths
    assert all(path == database_path for path in closed_paths)
