from app.domain import JobRecord, JobStage, JobStatus
from app.infrastructure.repositories.base import Repository


class JobService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def create_job(self, document_id: str, collection: str) -> JobRecord:
        return self.repository.create_job(document_id=document_id, collection=collection)

    def attach_rq_job(self, job_id: str, rq_job_id: str) -> JobRecord:
        self.repository.set_job_rq_id(job_id, rq_job_id)
        return self.repository.get_job(job_id)

    def get_job(self, job_id: str) -> JobRecord:
        return self.repository.get_job(job_id)

    def get_job_by_rq_id(self, rq_job_id: str) -> JobRecord:
        return self.repository.get_job_by_rq_id(rq_job_id)

    def mark_running(self, job_id: str, stage: JobStage, progress: int) -> JobRecord:
        self.repository.update_job(
            job_id=job_id,
            status=JobStatus.RUNNING,
            stage=stage,
            progress=progress,
            error=None,
        )
        return self.repository.get_job(job_id)

    def update_progress(self, job_id: str, stage: JobStage, progress: int) -> JobRecord:
        self.repository.update_job(
            job_id=job_id,
            status=JobStatus.RUNNING,
            stage=stage,
            progress=progress,
            error=None,
        )
        return self.repository.get_job(job_id)

    def mark_succeeded(self, job_id: str) -> JobRecord:
        self.repository.update_job(
            job_id=job_id,
            status=JobStatus.SUCCEEDED,
            stage=JobStage.DONE,
            progress=100,
            error=None,
        )
        return self.repository.get_job(job_id)

    def mark_failed(self, job_id: str, error: str) -> JobRecord:
        current = self.repository.get_job(job_id)
        self.repository.update_job(
            job_id=job_id,
            status=JobStatus.FAILED,
            stage=current.stage,
            progress=current.progress,
            error=error,
        )
        return self.repository.get_job(job_id)
