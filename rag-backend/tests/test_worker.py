from dataclasses import dataclass
from unittest.mock import Mock, patch

import pytest

from app.domain import JobStatus
from app.errors import NonRetryableIngestionError
from app.workers.ingest_worker import (
    ingest_document_job,
    rq_retry_is_exhausted,
)


@dataclass(frozen=True)
class FakeAppJob:
    id: str
    document_id: str
    collection: str
    status: JobStatus = JobStatus.QUEUED


class FakeRqJob:
    def __init__(
        self,
        id: str = "rq-job-123",
        retries_left: int | None = 1,
    ) -> None:
        self.id = id
        self.retries_left = retries_left


def test_ingest_document_job_requires_rq_current_job() -> None:
    with patch("app.workers.ingest_worker.get_current_job", return_value=None):
        with pytest.raises(RuntimeError, match="must run inside an RQ worker"):
            ingest_document_job("doc_123", "docs")


def test_ingest_document_job_loads_matching_app_job_and_ingests_document() -> None:
    rq_job = FakeRqJob()
    app_job = FakeAppJob(id="job_123", document_id="doc_123", collection="docs")
    job_service = Mock()
    job_service.get_job_by_rq_id.return_value = app_job
    ingestion_service = Mock()

    with (
        patch("app.workers.ingest_worker.get_current_job", return_value=rq_job),
        patch("app.workers.ingest_worker.get_job_service", return_value=job_service),
        patch("app.workers.ingest_worker.get_ingestion_service", return_value=ingestion_service),
    ):
        ingest_document_job("doc_123", "docs")

    job_service.get_job_by_rq_id.assert_called_once_with("rq-job-123")
    ingestion_service.ingest_document.assert_called_once_with("job_123", "doc_123", "docs")


@pytest.mark.parametrize("status", [JobStatus.FAILED, JobStatus.SUCCEEDED])
def test_ingest_document_job_skips_terminal_app_jobs(status: JobStatus) -> None:
    rq_job = FakeRqJob()
    app_job = FakeAppJob(id="job_123", document_id="doc_123", collection="docs", status=status)
    job_service = Mock()
    job_service.get_job_by_rq_id.return_value = app_job
    ingestion_service = Mock()

    with (
        patch("app.workers.ingest_worker.get_current_job", return_value=rq_job),
        patch("app.workers.ingest_worker.get_job_service", return_value=job_service),
        patch("app.workers.ingest_worker.get_ingestion_service", return_value=ingestion_service),
    ):
        ingest_document_job("doc_123", "docs")

    job_service.get_job_by_rq_id.assert_called_once_with("rq-job-123")
    ingestion_service.ingest_document.assert_not_called()


def test_ingest_document_job_retries_running_app_jobs() -> None:
    rq_job = FakeRqJob()
    app_job = FakeAppJob(id="job_123", document_id="doc_123", collection="docs", status=JobStatus.RUNNING)
    job_service = Mock()
    job_service.get_job_by_rq_id.return_value = app_job
    ingestion_service = Mock()

    with (
        patch("app.workers.ingest_worker.get_current_job", return_value=rq_job),
        patch("app.workers.ingest_worker.get_job_service", return_value=job_service),
        patch("app.workers.ingest_worker.get_ingestion_service", return_value=ingestion_service),
    ):
        ingest_document_job("doc_123", "docs")

    job_service.get_job_by_rq_id.assert_called_once_with("rq-job-123")
    ingestion_service.ingest_document.assert_called_once_with("job_123", "doc_123", "docs")


def test_ingest_document_job_marks_retry_exhausted_when_rq_reports_no_retries_left() -> None:
    rq_job = FakeRqJob(retries_left=0)
    app_job = FakeAppJob(id="job_123", document_id="doc_123", collection="docs")
    job_service = Mock()
    job_service.get_job_by_rq_id.return_value = app_job
    ingestion_service = Mock()
    ingestion_service.ingest_document.side_effect = RuntimeError("embedding unavailable")

    with (
        patch("app.workers.ingest_worker.get_current_job", return_value=rq_job),
        patch("app.workers.ingest_worker.get_job_service", return_value=job_service),
        patch("app.workers.ingest_worker.get_ingestion_service", return_value=ingestion_service),
    ):
        with pytest.raises(RuntimeError, match="embedding unavailable"):
            ingest_document_job("doc_123", "docs")

    ingestion_service.mark_retry_exhausted.assert_called_once_with(
        "job_123",
        "doc_123",
        "embedding unavailable",
    )


def test_ingest_document_job_redacts_retry_exhausted_error_before_persisting() -> None:
    rq_job = FakeRqJob(retries_left=0)
    app_job = FakeAppJob(id="job_123", document_id="doc_123", collection="docs")
    job_service = Mock()
    job_service.get_job_by_rq_id.return_value = app_job
    ingestion_service = Mock()
    ingestion_service.ingest_document.side_effect = RuntimeError(
        "failed at C:/secrets/private.db Authorization: Bearer sk-secret-token"
    )

    with (
        patch("app.workers.ingest_worker.get_current_job", return_value=rq_job),
        patch("app.workers.ingest_worker.get_job_service", return_value=job_service),
        patch("app.workers.ingest_worker.get_ingestion_service", return_value=ingestion_service),
    ):
        with pytest.raises(RuntimeError, match="failed"):
            ingest_document_job("doc_123", "docs")

    persisted_error = ingestion_service.mark_retry_exhausted.call_args.args[2]
    assert "private.db" not in persisted_error
    assert "sk-secret-token" not in persisted_error


def test_ingest_document_job_consumes_nonretryable_ingestion_errors() -> None:
    rq_job = FakeRqJob(retries_left=2)
    app_job = FakeAppJob(id="job_123", document_id="doc_123", collection="docs")
    job_service = Mock()
    job_service.get_job_by_rq_id.return_value = app_job
    ingestion_service = Mock()
    ingestion_service.ingest_document.side_effect = NonRetryableIngestionError("empty")

    with (
        patch("app.workers.ingest_worker.get_current_job", return_value=rq_job),
        patch("app.workers.ingest_worker.get_job_service", return_value=job_service),
        patch("app.workers.ingest_worker.get_ingestion_service", return_value=ingestion_service),
    ):
        ingest_document_job("doc_123", "docs")

    ingestion_service.ingest_document.assert_called_once_with("job_123", "doc_123", "docs")
    ingestion_service.mark_retry_exhausted.assert_not_called()


@pytest.mark.parametrize(
    ("retries_left", "expected"),
    [
        (0, True),
        (1, False),
        (None, False),
    ],
)
def test_rq_retry_is_exhausted_uses_only_explicit_retries_left(
    retries_left: int | None,
    expected: bool,
) -> None:
    assert rq_retry_is_exhausted(FakeRqJob(retries_left=retries_left)) is expected
