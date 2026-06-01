from pathlib import Path

from app.domain import JobStage
from app.errors import NonRetryableIngestionError, RetryableIngestionError
from app.infrastructure.chunkers.base import Chunker
from app.infrastructure.embeddings.base import EmbeddingProvider
from app.infrastructure.parsers.base import DocumentParser
from app.infrastructure.repositories.base import Repository
from app.infrastructure.vectorstores.base import VectorStore
from app.retrieval.bm25_indexer import MemoryBM25Indexer
from app.sanitization import sanitize_error_message
from app.services.job_service import JobService
from app.observability import get_logger

logger = get_logger(__name__)


class IngestionService:
    def __init__(
        self,
        repository: Repository,
        job_service: JobService,
        parser: DocumentParser,
        chunker: Chunker,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        bm25_indexer: MemoryBM25Indexer | None = None,
    ) -> None:
        self.repository = repository
        self.job_service = job_service
        self.parser = parser
        self.chunker = chunker
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.bm25_indexer = bm25_indexer

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

            if self.bm25_indexer is not None:
                chunk_count = self._ingest_dual(job_id, document_id, collection, document, parsed_text)
            else:
                chunk_count = self._ingest_single(job_id, document_id, collection, document, parsed_text)

            self.repository.mark_document_indexed(document_id, chunk_count=chunk_count)
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

    def _ingest_single(
        self,
        job_id: str,
        document_id: str,
        collection: str,
        document: object,
        parsed_text: str,
    ) -> int:
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

        return len(chunks)

    def _ingest_dual(
        self,
        job_id: str,
        document_id: str,
        collection: str,
        document: object,
        parsed_text: str,
    ) -> int:
        dual_split = getattr(self.chunker, "dual_split", None)
        if dual_split is None:
            return self._ingest_single(job_id, document_id, collection, document, parsed_text)

        try:
            parents, children = dual_split(parsed_text)
        except (NonRetryableIngestionError, RetryableIngestionError):
            raise
        except ValueError as exc:
            detail = sanitize_error_message(str(exc))
            raise NonRetryableIngestionError(f"Document dual chunking failed: {detail}") from exc

        logger.info(
            "dual_chunk_completed",
            extra={"extra_fields": {
                "document_id": document_id,
                "parent_count": len(parents),
                "child_count": len(children),
            }},
        )

        for p_idx, parent in enumerate(parents):
            parent_id = f"{document_id}:parent:{p_idx}"
            self.repository.store_parent_chunk(
                id=parent_id,
                document_id=document_id,
                collection=collection,
                text=parent.text,
                chunk_index=p_idx,
            )

        def _assign_parent(child_index: int, total_children: int, total_parents: int) -> int:
            if total_parents == 0:
                return 0
            p = int(child_index * total_parents / total_children)
            return min(p, total_parents - 1)

        child_texts = [child.text for child in children]
        child_ids = [f"{document_id}:{c_idx}" for c_idx, _ in enumerate(children)]
        child_metadatas = [
            {
                "document_id": document.id,
                "filename": document.filename,
                "source_file": document.filename,
                "collection": collection,
                "chunk_index": child.chunk_index,
                "upload_time": document.created_at,
                "source": "upload",
                "content_hash": document.content_hash,
                "parent_id": f"{document_id}:parent:{_assign_parent(c_idx, len(children), len(parents))}",
                "type": "child",
                **child.metadata,
            }
            for c_idx, child in enumerate(children)
        ]

        self.job_service.update_progress(job_id, JobStage.EMBEDDING, 65)
        embeddings = self.embedding_provider.embed_texts(child_texts)

        self.job_service.update_progress(job_id, JobStage.WRITING, 90)
        self.vector_store.delete_chunks(collection=collection, where={"document_id": document_id})
        self.vector_store.upsert_chunks(
            collection=collection,
            ids=child_ids,
            texts=child_texts,
            embeddings=embeddings,
            metadatas=child_metadatas,
        )

        self.repository.replace_chunks(
            document_id=document_id,
            collection=collection,
            chunks=[
                {
                    "chunk_index": child.chunk_index,
                    "chroma_id": child_ids[i],
                    "content_preview": child.text[:200],
                    "token_count": child.token_count,
                    "source_file": document.filename,
                    "upload_time": document.created_at,
                    "parent_id": child_metadatas[i]["parent_id"],
                    "type": "child",
                }
                for i, child in enumerate(children)
            ],
        )

        for child_text in child_texts:
            self.bm25_indexer.add(child_text)

        return len(children)

    def mark_retry_exhausted(self, job_id: str, document_id: str, error: str) -> None:
        sanitized_error = sanitize_error_message(error)
        self.repository.mark_document_failed(document_id, sanitized_error)
        self.job_service.mark_failed(job_id, sanitized_error)


def ingest_document(job_id: str, document_id: str, collection: str) -> None:
    raise RuntimeError("Configure a worker entrypoint with concrete ingestion dependencies.")
