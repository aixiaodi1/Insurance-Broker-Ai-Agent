from dataclasses import asdict

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.dependencies import get_document_service, get_repository
from app.domain import DocumentRecord, JobRecord
from app.errors import ValidationError
from app.infrastructure.repositories.base import Repository
from app.services.document_service import DocumentService


router = APIRouter(prefix="/documents", tags=["documents"])


def serialize_document(document: DocumentRecord) -> dict:
    data = asdict(document)
    data["status"] = document.status.value
    return data


def serialize_job(job: JobRecord) -> dict:
    data = asdict(job)
    data["status"] = job.status.value
    data["stage"] = job.stage.value
    return data


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
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

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
