import logging
from typing import Any

from rq import get_current_job

from app.dependencies import get_ingestion_service, get_job_service
from app.domain import JobStatus
from app.errors import NonRetryableIngestionError
from app.sanitization import sanitize_error_message

logger = logging.getLogger(__name__)


def ingest_document_job(document_id: str, collection: str) -> None:
    rq_job = get_current_job()
    if rq_job is None:
        raise RuntimeError("ingest_document_job must run inside an RQ worker")

    job_service = get_job_service()
    app_job = job_service.get_job_by_rq_id(rq_job.id)
    if app_job.status in {JobStatus.FAILED, JobStatus.SUCCEEDED}:
        logger.info(
            "Skipping ingestion for app job %s with status %s, document %s, RQ job %s",
            app_job.id,
            app_job.status,
            document_id,
            rq_job.id,
        )
        return

    ingestion_service = get_ingestion_service()

    try:
        ingestion_service.ingest_document(app_job.id, document_id, collection)
    except NonRetryableIngestionError:
        logger.exception(
            "Ingestion worker consumed non-retryable failure for app job %s, document %s, RQ job %s",
            app_job.id,
            document_id,
            rq_job.id,
        )
    except Exception as exc:
        logger.exception(
            "Ingestion worker failed for app job %s, document %s, RQ job %s",
            app_job.id,
            document_id,
            rq_job.id,
        )
        if rq_retry_is_exhausted(rq_job):
            ingestion_service.mark_retry_exhausted(app_job.id, document_id, sanitize_error_message(str(exc)))
        raise


def rq_retry_is_exhausted(rq_job: Any) -> bool:
    retries_left = getattr(rq_job, "retries_left", None)
    return isinstance(retries_left, int) and retries_left <= 0
