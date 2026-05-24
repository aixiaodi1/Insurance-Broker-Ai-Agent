from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_repository
from app.infrastructure.repositories.base import Repository


router = APIRouter(tags=["ingestion_jobs"])


@router.get("/jobs/{job_id}")
def get_job(job_id: str, repository: Repository = Depends(get_repository)) -> dict:
    try:
        job = repository.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job not found: {job_id}") from exc

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
