from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.dependencies import get_document_service, get_repository
from app.domain import DocumentRecord, JobRecord
from app.errors import ValidationError
from app.infrastructure.repositories.base import Repository
from app.services.document_service import DocumentService


router = APIRouter(prefix="/documents", tags=["documents"])


def serialize_document(document: DocumentRecord) -> dict:
    return {
        "document_id": document.id,
        "filename": document.filename,
        "collection": document.collection,
        "status": document.status.value,
        "mime_type": document.mime_type,
        "file_size": document.file_size,
        "chunk_count": document.chunk_count,
        "error": document.error,
        "created_at": document.created_at,
        "indexed_at": document.indexed_at,
    }


def serialize_job(job: JobRecord) -> dict:
    return {
        "job_id": job.id,
        "document_id": job.document_id,
        "status": job.status.value,
        "stage": job.stage.value,
        "progress": job.progress,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


@router.post("/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    collection: str = Form(...),
    document_service: DocumentService = Depends(get_document_service),
) -> dict:
    try:
        result = await document_service.upload_files(files, collection)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Document upload failed") from exc

    return {
        "documents": [serialize_document(document) for document in result["documents"]],
        "jobs": [serialize_job(job) for job in result["jobs"]],
    }


@router.get("")
def list_documents(
    collection: str | None = None,
    repository: Repository = Depends(get_repository),
) -> dict:
    return {"documents": [serialize_document(document) for document in repository.list_documents(collection)]}
