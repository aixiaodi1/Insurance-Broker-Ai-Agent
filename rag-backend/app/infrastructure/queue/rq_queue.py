from redis import Redis
from rq import Queue, Retry

from app.infrastructure.queue.base import IngestionQueueItem


INGESTION_JOB_PATH = "app.workers.ingest_worker.ingest_document_job"
INGESTION_RETRY = Retry(max=3, interval=[10, 30, 60])
INGESTION_JOB_TIMEOUT = "30m"
INGESTION_FAILURE_TTL = 86400


class RqQueueClient:
    def __init__(self, redis_url: str, queue_name: str) -> None:
        self.redis = Redis.from_url(redis_url)
        self.queue = Queue(queue_name, connection=self.redis)

    def enqueue_ingestion(self, document_id: str, collection: str, app_job_id: str | None = None) -> str:
        return self.enqueue_ingestions(
            [IngestionQueueItem(document_id=document_id, collection=collection, app_job_id=app_job_id)]
        )[0]

    def enqueue_ingestions(self, items: list[IngestionQueueItem]) -> list[str]:
        job_datas = [
            self.queue.prepare_data(
                INGESTION_JOB_PATH,
                args=(item.document_id, item.collection),
                retry=INGESTION_RETRY,
                timeout=INGESTION_JOB_TIMEOUT,
                failure_ttl=INGESTION_FAILURE_TTL,
                job_id=item.app_job_id,
            )
            for item in items
        ]
        with self.redis.pipeline() as pipeline:
            jobs = self.queue.enqueue_many(job_datas, pipeline=pipeline)
            pipeline.execute()
        return [job.id for job in jobs]
