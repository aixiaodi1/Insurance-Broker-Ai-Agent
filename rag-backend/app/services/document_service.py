import inspect
import shutil
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from app.config import Settings
from app.errors import ValidationError
from app.infrastructure.queue.base import IngestionQueueItem, QueueClient
from app.infrastructure.repositories.base import Repository
from app.sanitization import sanitize_error_message
from app.services.job_service import JobService


_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class _ValidatedUpload:
    filename: str
    extension: str
    content: bytes
    content_type: str
    content_hash: str
    file_size: int


class DocumentService:
    """Upload service.

    File objects are expected to expose ``filename`` and ``read()``. ``read`` may
    be sync or async, matching FastAPI's UploadFile interface.
    """

    def __init__(
        self,
        repository: Repository,
        job_service: JobService,
        queue_client: QueueClient,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.job_service = job_service
        self.queue_client = queue_client
        self.settings = settings

    async def upload_files(self, files: list, collection: str) -> dict:
        normalized_collection = collection.strip()
        if not normalized_collection:
            raise ValidationError("Collection is required.")

        validated_uploads = []
        total_upload_size = 0
        for upload in files:
            filename = Path(upload.filename).name
            extension = Path(filename).suffix.lower()
            self._validate_extension(extension)
            content, file_size, content_hash, total_upload_size = await self._read_file(upload, total_upload_size)

            validated_uploads.append(
                _ValidatedUpload(
                    filename=filename,
                    extension=extension,
                    content=content,
                    content_type=getattr(upload, "content_type", "") or "application/octet-stream",
                    content_hash=content_hash,
                    file_size=file_size,
                )
            )

        documents = []
        jobs = []
        created_document_ids = []
        created_job_ids = []
        saved_upload_dirs = []
        queue_items = []
        try:
            for upload in validated_uploads:
                placeholder_path = self.settings.upload_dir / "_pending" / upload.filename
                document = self.repository.create_document(
                    filename=upload.filename,
                    collection=normalized_collection,
                    mime_type=upload.content_type,
                    file_size=upload.file_size,
                    source_path=str(placeholder_path),
                    content_hash=upload.content_hash,
                )
                created_document_ids.append(document.id)

                final_path = self.settings.upload_dir / document.id / f"original{upload.extension}"
                saved_upload_dirs.append(final_path.parent)
                final_path.parent.mkdir(parents=True, exist_ok=True)
                final_path.write_bytes(upload.content)
                document = self.repository.update_document_source_path(document.id, str(final_path))

                job = self.job_service.create_job(document.id, normalized_collection)
                created_job_ids.append(job.id)
                job = self.job_service.attach_rq_job(job.id, job.id)

                documents.append(document)
                jobs.append(job)
                queue_items.append(
                    IngestionQueueItem(
                        document_id=document.id,
                        collection=normalized_collection,
                        app_job_id=job.id,
                    )
                )

            rq_job_ids = self.queue_client.enqueue_ingestions(queue_items) if queue_items else []
            if len(rq_job_ids) != len(jobs):
                raise RuntimeError("Queue returned an unexpected number of jobs.")
            for index, rq_job_id in enumerate(rq_job_ids):
                if str(rq_job_id) != jobs[index].rq_job_id:
                    jobs[index] = self.job_service.attach_rq_job(jobs[index].id, str(rq_job_id))
        except Exception as exc:
            error = sanitize_error_message(str(exc))
            self._compensate_batch_best_effort(created_document_ids, created_job_ids, saved_upload_dirs, error)
            raise

        return {"documents": documents, "jobs": jobs}

    async def _read_file(self, upload, current_batch_size: int) -> tuple[bytes, int, str, int]:
        chunks: list[bytes] = []
        digest = sha256()
        file_size = 0

        while True:
            chunk = upload.read(_UPLOAD_READ_CHUNK_BYTES)
            if inspect.isawaitable(chunk):
                chunk = await chunk
            if not isinstance(chunk, bytes):
                raise ValidationError("Uploaded file content must be bytes.")
            if not chunk:
                break

            chunks.append(chunk)
            digest.update(chunk)
            file_size += len(chunk)
            current_batch_size += len(chunk)
            self._validate_size(file_size)
            self._validate_batch_size(current_batch_size)

        return b"".join(chunks), file_size, digest.hexdigest(), current_batch_size

    def _validate_extension(self, extension: str) -> None:
        if extension not in self.settings.allowed_extensions:
            raise ValidationError(f"Unsupported file extension: {extension}.")

    def _validate_size(self, size_bytes: int) -> None:
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        if size_bytes > max_bytes:
            raise ValidationError(f"Uploaded file exceeds {self.settings.max_upload_mb} MB.")

    def _validate_batch_size(self, size_bytes: int) -> None:
        max_bytes = self.settings.max_upload_batch_mb * 1024 * 1024
        if size_bytes > max_bytes:
            raise ValidationError(f"Uploaded batch exceeds {self.settings.max_upload_batch_mb} MB.")

    def _compensate_batch_best_effort(
        self,
        document_ids: list[str],
        job_ids: list[str],
        upload_dirs: list[Path],
        error: str,
    ) -> None:
        for document_id in document_ids:
            try:
                self.repository.mark_document_failed(document_id, error)
            except Exception:
                pass

        for job_id in job_ids:
            try:
                self.job_service.mark_failed(job_id, error)
            except Exception:
                pass

        for upload_dir in upload_dirs:
            self._remove_upload_dir_best_effort(upload_dir)

    def _remove_upload_dir_best_effort(self, upload_dir: Path) -> None:
        try:
            upload_root = self.settings.upload_dir.resolve()
            document_dir = upload_dir.resolve()
            if document_dir.parent != upload_root:
                return
            if document_dir.exists():
                shutil.rmtree(document_dir)
        except Exception:
            pass
