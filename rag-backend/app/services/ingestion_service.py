from pathlib import Path

from app.domain import JobStage
from app.errors import NonRetryableIngestionError, RetryableIngestionError
from app.infrastructure.chunkers.base import Chunker
from app.infrastructure.embeddings.base import EmbeddingProvider
from app.infrastructure.parsers.base import DocumentParser
from app.infrastructure.repositories.base import Repository
from app.infrastructure.vectorstores.base import VectorStore
from app.sanitization import sanitize_error_message
from app.services.job_service import JobService


class IngestionService:
    def __init__(
        self,
        repository: Repository,
        job_service: JobService,
        parser: DocumentParser,
        chunker: Chunker,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> None:
        self.repository = repository
        self.job_service = job_service
        self.parser = parser
        self.chunker = chunker
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    def ingest_document(self, job_id: str, document_id: str, collection: str) -> None:
        try:
            document = self.repository.get_document(document_id)
            source_path = Path(document.source_path)

            self.repository.mark_document_indexing(document_id)
            self.job_service.mark_running(job_id, JobStage.PARSING, 20)
            parsed_text = self.parser.parse(source_path)

            if not parsed_text.strip():
                raise NonRetryableIngestionError("Parsed document text is empty.")

            text_path = source_path.parent / "extracted.txt"
            try:
                text_path.write_text(parsed_text, encoding="utf-8")
            except OSError as exc:
                raise RetryableIngestionError(f"Writing extracted text failed: {sanitize_error_message(str(exc))}") from exc
            self.repository.set_document_text_path(document_id, str(text_path))

            self.job_service.update_progress(job_id, JobStage.CHUNKING, 35)
            try:
                chunks = self.chunker.split(parsed_text)
            except (NonRetryableIngestionError, RetryableIngestionError):
                raise
            except ValueError as exc:
                detail = sanitize_error_message(str(exc))
                raise NonRetryableIngestionError(f"Document chunking failed: {detail}") from exc

            texts = [chunk.text for chunk in chunks]
            self.job_service.update_progress(job_id, JobStage.EMBEDDING, 65)
            embeddings = self.embedding_provider.embed_texts(texts)

            ids = [f"{document_id}:{chunk.chunk_index}" for chunk in chunks]
            metadatas = [
                {
                    "document_id": document.id,
                    "filename": document.filename,
                    "source_file": document.filename,
                    "collection": collection,
                    "chunk_index": chunk.chunk_index,
                    "upload_time": document.created_at,
                    "source": "upload",
                    "content_hash": document.content_hash,
                    **chunk.metadata,
                }
                for chunk in chunks
            ]
            self.job_service.update_progress(job_id, JobStage.WRITING, 90)
            self.vector_store.delete_chunks(collection=collection, where={"document_id": document_id})
            self.vector_store.upsert_chunks(
                collection=collection,
                ids=ids,
                texts=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )

            self.repository.replace_chunks(
                document_id=document_id,
                collection=collection,
                chunks=[
                    {
                        "chunk_index": chunk.chunk_index,
                        "chroma_id": chroma_id,
                        "content_preview": chunk.text[:200],
                        "token_count": chunk.token_count,
                        "source_file": document.filename,
                        "upload_time": document.created_at,
                    }
                    for chunk, chroma_id in zip(chunks, ids, strict=True)
                ],
            )
            self.repository.mark_document_indexed(document_id, chunk_count=len(chunks))
            self.job_service.mark_succeeded(job_id)
        except NonRetryableIngestionError as exc:
            error = sanitize_error_message(str(exc))
            self.repository.mark_document_failed(document_id, error)
            self.job_service.mark_failed(job_id, error)
            raise
        except RetryableIngestionError as exc:
            error = sanitize_error_message(str(exc))
            current = self.repository.get_job(job_id)
            self.repository.update_job(
                job_id=job_id,
                status=current.status,
                stage=current.stage,
                progress=current.progress,
                error=error,
            )
            raise

    def mark_retry_exhausted(self, job_id: str, document_id: str, error: str) -> None:
        sanitized_error = sanitize_error_message(error)
        self.repository.mark_document_failed(document_id, sanitized_error)
        self.job_service.mark_failed(job_id, sanitized_error)


def ingest_document(job_id: str, document_id: str, collection: str) -> None:
    raise RuntimeError("Configure a worker entrypoint with concrete ingestion dependencies.")
