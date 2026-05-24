from unittest.mock import MagicMock, Mock, patch

from rq import Retry

from app.infrastructure.queue.base import IngestionQueueItem
from app.infrastructure.queue.rq_queue import RqQueueClient


def test_rq_queue_client_enqueues_ingestion_job_with_retry_policy() -> None:
    redis = Mock()
    pipeline = Mock()
    redis.pipeline.return_value = MagicMock()
    redis.pipeline.return_value.__enter__.return_value = pipeline
    job = Mock(id="rq-job-123")
    queue = Mock()
    queue.prepare_data.return_value = "prepared"
    queue.enqueue_many.return_value = [job]

    with (
        patch("app.infrastructure.queue.rq_queue.Redis.from_url", return_value=redis) as redis_from_url,
        patch("app.infrastructure.queue.rq_queue.Queue", return_value=queue) as queue_cls,
    ):
        client = RqQueueClient(redis_url="redis://redis:6379/2", queue_name="ingestion")

    rq_job_id = client.enqueue_ingestion("doc_123", "docs")

    assert rq_job_id == "rq-job-123"
    redis_from_url.assert_called_once_with("redis://redis:6379/2")
    queue_cls.assert_called_once_with("ingestion", connection=redis)
    queue.prepare_data.assert_called_once()
    function_path = queue.prepare_data.call_args.args[0]
    assert function_path == "app.workers.ingest_worker.ingest_document_job"
    assert queue.prepare_data.call_args.kwargs["args"] == ("doc_123", "docs")
    assert queue.prepare_data.call_args.kwargs["timeout"] == "30m"
    assert queue.prepare_data.call_args.kwargs["failure_ttl"] == 86400
    retry = queue.prepare_data.call_args.kwargs["retry"]
    assert isinstance(retry, Retry)
    assert retry.max == 3
    assert retry.intervals == [10, 30, 60]
    queue.enqueue_many.assert_called_once_with(["prepared"], pipeline=pipeline)
    pipeline.execute.assert_called_once_with()


def test_rq_queue_client_can_use_app_job_id_as_rq_job_id() -> None:
    redis = Mock()
    pipeline = Mock()
    redis.pipeline.return_value = MagicMock()
    redis.pipeline.return_value.__enter__.return_value = pipeline
    job = Mock(id="job_123")
    queue = Mock()
    queue.prepare_data.return_value = "prepared"
    queue.enqueue_many.return_value = [job]

    with (
        patch("app.infrastructure.queue.rq_queue.Redis.from_url", return_value=redis),
        patch("app.infrastructure.queue.rq_queue.Queue", return_value=queue),
    ):
        client = RqQueueClient(redis_url="redis://redis:6379/2", queue_name="ingestion")

    rq_job_id = client.enqueue_ingestion("doc_123", "docs", app_job_id="job_123")

    assert rq_job_id == "job_123"
    assert queue.prepare_data.call_args.kwargs["job_id"] == "job_123"
    queue.enqueue_many.assert_called_once_with(["prepared"], pipeline=pipeline)
    pipeline.execute.assert_called_once_with()


def test_rq_queue_client_batch_enqueues_ingestions_with_pipeline_and_retry_policy() -> None:
    redis = Mock()
    pipeline = Mock()
    redis.pipeline.return_value = MagicMock()
    redis.pipeline.return_value.__enter__.return_value = pipeline
    jobs = [Mock(id="job_1"), Mock(id="job_2")]
    queue = Mock()
    queue.prepare_data.side_effect = ["prepared-1", "prepared-2"]
    queue.enqueue_many.return_value = jobs

    with (
        patch("app.infrastructure.queue.rq_queue.Redis.from_url", return_value=redis),
        patch("app.infrastructure.queue.rq_queue.Queue", return_value=queue),
    ):
        client = RqQueueClient(redis_url="redis://redis:6379/2", queue_name="ingestion")

    rq_job_ids = client.enqueue_ingestions(
        [
            IngestionQueueItem(document_id="doc_1", collection="docs", app_job_id="job_1"),
            IngestionQueueItem(document_id="doc_2", collection="docs", app_job_id="job_2"),
        ]
    )

    assert rq_job_ids == ["job_1", "job_2"]
    assert queue.prepare_data.call_count == 2
    first_call = queue.prepare_data.call_args_list[0]
    assert first_call.args == ("app.workers.ingest_worker.ingest_document_job",)
    assert first_call.kwargs["args"] == ("doc_1", "docs")
    assert first_call.kwargs["job_id"] == "job_1"
    assert first_call.kwargs["timeout"] == "30m"
    assert first_call.kwargs["failure_ttl"] == 86400
    retry = first_call.kwargs["retry"]
    assert isinstance(retry, Retry)
    assert retry.max == 3
    assert retry.intervals == [10, 30, 60]
    second_call = queue.prepare_data.call_args_list[1]
    assert second_call.kwargs["args"] == ("doc_2", "docs")
    assert second_call.kwargs["job_id"] == "job_2"
    queue.enqueue_many.assert_called_once_with(["prepared-1", "prepared-2"], pipeline=pipeline)
    pipeline.execute.assert_called_once_with()


def test_rq_queue_client_single_enqueue_delegates_to_batch_enqueue() -> None:
    redis = Mock()
    pipeline = Mock()
    redis.pipeline.return_value = MagicMock()
    redis.pipeline.return_value.__enter__.return_value = pipeline
    queue = Mock()
    queue.prepare_data.return_value = "prepared"
    queue.enqueue_many.return_value = [Mock(id="job_123")]

    with (
        patch("app.infrastructure.queue.rq_queue.Redis.from_url", return_value=redis),
        patch("app.infrastructure.queue.rq_queue.Queue", return_value=queue),
    ):
        client = RqQueueClient(redis_url="redis://redis:6379/2", queue_name="ingestion")

    rq_job_id = client.enqueue_ingestion("doc_123", "docs", app_job_id="job_123")

    assert rq_job_id == "job_123"
    queue.enqueue.assert_not_called()
    queue.enqueue_many.assert_called_once_with(["prepared"], pipeline=pipeline)
    pipeline.execute.assert_called_once_with()
