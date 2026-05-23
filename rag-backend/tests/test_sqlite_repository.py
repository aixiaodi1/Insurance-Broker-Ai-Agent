from pathlib import Path

from app.domain import DocumentStatus, JobStage, JobStatus
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
    repo.add_chunks(
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
