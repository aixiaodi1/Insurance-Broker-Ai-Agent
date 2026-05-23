import inspect
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.errors import ValidationError
from app.infrastructure.repositories.base import Repository
from app.services.job_service import JobService


class QueueClient(Protocol):
    def enqueue_ingestion(self, document_id: str, collection: str) -> str: ...


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

        documents = []
        jobs = []
        for upload in files:
            content = await self._read_file(upload)
            filename = Path(upload.filename).name
            extension = Path(filename).suffix.lower()
            self._validate_extension(extension)
            self._validate_size(len(content))

            content_hash = sha256(content).hexdigest()
            placeholder_path = self.settings.upload_dir / "_pending" / filename
            document = self.repository.create_document(
                filename=filename,
                collection=normalized_collection,
                mime_type=getattr(upload, "content_type", "") or "application/octet-stream",
                file_size=len(content),
                source_path=str(placeholder_path),
                content_hash=content_hash,
            )

            final_path = self.settings.upload_dir / document.id / f"original{extension}"
            final_path.parent.mkdir(parents=True, exist_ok=True)
            final_path.write_bytes(content)
            document = self.repository.update_document_source_path(document.id, str(final_path))

            job = self.job_service.create_job(document.id, normalized_collection)
            rq_job = self.queue_client.enqueue_ingestion(document.id, normalized_collection)
            rq_job_id = getattr(rq_job, "id", rq_job)
            job = self.job_service.attach_rq_job(job.id, str(rq_job_id))

            documents.append(document)
            jobs.append(job)

        return {"documents": documents, "jobs": jobs}

    async def _read_file(self, upload) -> bytes:
        content = upload.read()
        if inspect.isawaitable(content):
            content = await content
        if not isinstance(content, bytes):
            raise ValidationError("Uploaded file content must be bytes.")
        return content

    def _validate_extension(self, extension: str) -> None:
        if extension not in self.settings.allowed_extensions:
            raise ValidationError(f"Unsupported file extension: {extension}.")

    def _validate_size(self, size_bytes: int) -> None:
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        if size_bytes > max_bytes:
            raise ValidationError(f"Uploaded file exceeds {self.settings.max_upload_mb} MB.")
