from unittest.mock import Mock, patch

from rq import Retry

from app.infrastructure.queue.rq_queue import RqQueueClient


def test_rq_queue_client_enqueues_ingestion_job_with_retry_policy() -> None:
    redis = Mock()
    job = Mock(id="rq-job-123")
    queue = Mock()
    queue.enqueue.return_value = job

    with (
        patch("app.infrastructure.queue.rq_queue.Redis.from_url", return_value=redis) as redis_from_url,
        patch("app.infrastructure.queue.rq_queue.Queue", return_value=queue) as queue_cls,
    ):
        client = RqQueueClient(redis_url="redis://redis:6379/2", queue_name="ingestion")

    rq_job_id = client.enqueue_ingestion("doc_123", "docs")

    assert rq_job_id == "rq-job-123"
    redis_from_url.assert_called_once_with("redis://redis:6379/2")
    queue_cls.assert_called_once_with("ingestion", connection=redis)
    queue.enqueue.assert_called_once()
    function_path, document_id, collection = queue.enqueue.call_args.args
    assert function_path == "app.workers.ingest_worker.ingest_document_job"
    assert document_id == "doc_123"
    assert collection == "docs"
    assert queue.enqueue.call_args.kwargs["job_timeout"] == "30m"
    assert queue.enqueue.call_args.kwargs["failure_ttl"] == 86400
    retry = queue.enqueue.call_args.kwargs["retry"]
    assert isinstance(retry, Retry)
    assert retry.max == 3
    assert retry.intervals == [10, 30, 60]
