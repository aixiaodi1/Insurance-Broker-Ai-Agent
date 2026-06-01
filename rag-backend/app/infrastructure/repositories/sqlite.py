import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from app.domain import DocumentRecord, DocumentStatus, JobRecord, JobStage, JobStatus


class SQLiteRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.database_path = Path(database_url.removeprefix("sqlite:///"))

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    source_path TEXT NOT NULL,
                    text_path TEXT,
                    content_hash TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    indexed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id TEXT PRIMARY KEY,
                    rq_job_id TEXT UNIQUE,
                    document_id TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    FOREIGN KEY (document_id) REFERENCES documents(id)
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chroma_id TEXT NOT NULL,
                    content_preview TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    source_file TEXT NOT NULL,
                    upload_time TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    parent_id TEXT,
                    type TEXT DEFAULT 'child',
                    FOREIGN KEY (document_id) REFERENCES documents(id)
                );
                """
            )
            self._migrate_chunks(connection)

    def _migrate_chunks(self, connection: sqlite3.Connection) -> None:
        existing = {row["name"] for row in connection.execute("PRAGMA table_info(chunks)").fetchall()}
        if "parent_id" not in existing:
            connection.execute("ALTER TABLE chunks ADD COLUMN parent_id TEXT")
        if "type" not in existing:
            connection.execute("ALTER TABLE chunks ADD COLUMN type TEXT DEFAULT 'child'")

    def store_parent_chunk(
        self,
        id: str,
        document_id: str,
        collection: str,
        text: str,
        chunk_index: int,
    ) -> None:
        created_at = self._now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO chunks (
                    id, document_id, collection, chunk_index, chroma_id,
                    content_preview, token_count, source_file, upload_time,
                    created_at, parent_id, type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    id,
                    document_id,
                    collection,
                    chunk_index,
                    id,
                    text,
                    len(text),
                    document_id,
                    created_at,
                    created_at,
                    None,
                    "parent",
                ),
            )

    def get_parent_chunk(self, parent_id: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT content_preview FROM chunks WHERE id = ? AND type = 'parent'",
                (parent_id,),
            ).fetchone()
        if row is None:
            return None
        return row["content_preview"]

    def list_all_child_texts(self) -> list[str]:
        with self._connection() as connection:
            try:
                rows = connection.execute(
                    "SELECT content_preview FROM chunks WHERE type = 'child' OR type IS NULL"
                ).fetchall()
            except sqlite3.OperationalError:
                rows = connection.execute(
                    "SELECT content_preview FROM chunks"
                ).fetchall()
        return [row["content_preview"] for row in rows]

    def create_document(
        self,
        filename: str,
        collection: str,
        mime_type: str,
        file_size: int,
        source_path: str,
        content_hash: str,
    ) -> DocumentRecord:
        document_id = f"doc_{uuid4().hex}"
        created_at = self._now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    id, filename, collection, status, mime_type, file_size,
                    source_path, text_path, content_hash, chunk_count, error,
                    created_at, indexed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    filename,
                    collection,
                    DocumentStatus.UPLOADED,
                    mime_type,
                    file_size,
                    source_path,
                    None,
                    content_hash,
                    0,
                    None,
                    created_at,
                    None,
                ),
            )
        return self.get_document(document_id)

    def get_document(self, document_id: str) -> DocumentRecord:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            raise KeyError(f"Document not found: {document_id}")
        return self._document_from_row(row)

    def list_documents(self, collection: str | None = None) -> list[DocumentRecord]:
        with self._connection() as connection:
            if collection is None:
                rows = connection.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM documents WHERE collection = ? ORDER BY created_at DESC",
                    (collection,),
                ).fetchall()
        return [self._document_from_row(row) for row in rows]

    def update_document_source_path(self, document_id: str, source_path: str) -> DocumentRecord:
        with self._connection() as connection:
            connection.execute(
                "UPDATE documents SET source_path = ? WHERE id = ?",
                (source_path, document_id),
            )
        return self.get_document(document_id)

    def mark_document_indexing(self, document_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE documents SET status = ?, error = NULL WHERE id = ?",
                (DocumentStatus.INDEXING, document_id),
            )

    def mark_document_indexed(self, document_id: str, chunk_count: int) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE documents
                SET status = ?, chunk_count = ?, error = NULL, indexed_at = ?
                WHERE id = ?
                """,
                (DocumentStatus.INDEXED, chunk_count, self._now(), document_id),
            )

    def mark_document_failed(self, document_id: str, error: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE documents SET status = ?, error = ? WHERE id = ?",
                (DocumentStatus.FAILED, error, document_id),
            )

    def set_document_text_path(self, document_id: str, text_path: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE documents SET text_path = ? WHERE id = ?",
                (text_path, document_id),
            )

    def create_job(self, document_id: str, collection: str) -> JobRecord:
        job_id = f"job_{uuid4().hex}"
        created_at = self._now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO ingestion_jobs (
                    id, rq_job_id, document_id, collection, status, stage,
                    progress, error, created_at, updated_at, started_at, finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    None,
                    document_id,
                    collection,
                    JobStatus.QUEUED,
                    JobStage.UPLOADED,
                    5,
                    None,
                    created_at,
                    created_at,
                    None,
                    None,
                ),
            )
        return self.get_job(job_id)

    def set_job_rq_id(self, job_id: str, rq_job_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE ingestion_jobs SET rq_job_id = ?, updated_at = ? WHERE id = ?",
                (rq_job_id, self._now(), job_id),
            )

    def get_job(self, job_id: str) -> JobRecord:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Job not found: {job_id}")
        return self._job_from_row(row)

    def get_job_by_rq_id(self, rq_job_id: str) -> JobRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE rq_job_id = ?",
                (rq_job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Job not found for RQ id: {rq_job_id}")
        return self._job_from_row(row)

    def update_job(
        self,
        job_id: str,
        status: JobStatus,
        stage: JobStage,
        progress: int,
        error: str | None = None,
    ) -> None:
        existing = self.get_job(job_id)
        now = self._now()
        started_at = existing.started_at
        finished_at = existing.finished_at
        if status == JobStatus.RUNNING and started_at is None:
            started_at = now
        if status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
            finished_at = finished_at or now

        with self._connection() as connection:
            connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = ?, stage = ?, progress = ?, error = ?, updated_at = ?,
                    started_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, stage, progress, error, now, started_at, finished_at, job_id),
            )

    def replace_chunks(self, document_id: str, collection: str, chunks: list[dict]) -> None:
        created_at = self._now()
        rows = [
            (
                f"chunk_{uuid4().hex}",
                document_id,
                collection,
                chunk["chunk_index"],
                chunk["chroma_id"],
                chunk["content_preview"],
                chunk["token_count"],
                chunk["source_file"],
                chunk["upload_time"],
                created_at,
                chunk.get("parent_id"),
                chunk.get("type", "child"),
            )
            for chunk in chunks
        ]
        with self._connection() as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            connection.executemany(
                """
                INSERT INTO chunks (
                    id, document_id, collection, chunk_index, chroma_id,
                    content_preview, token_count, source_file, upload_time,
                    created_at, parent_id, type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def add_chunks(self, document_id: str, collection: str, chunks: list[dict]) -> None:
        self.replace_chunks(document_id, collection, chunks)

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _document_from_row(row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            filename=row["filename"],
            collection=row["collection"],
            status=DocumentStatus(row["status"]),
            mime_type=row["mime_type"],
            file_size=row["file_size"],
            source_path=row["source_path"],
            text_path=row["text_path"],
            content_hash=row["content_hash"],
            chunk_count=row["chunk_count"],
            error=row["error"],
            created_at=row["created_at"],
            indexed_at=row["indexed_at"],
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            rq_job_id=row["rq_job_id"],
            document_id=row["document_id"],
            collection=row["collection"],
            status=JobStatus(row["status"]),
            stage=JobStage(row["stage"]),
            progress=row["progress"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat()
