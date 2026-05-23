from redis import Redis
from rq import Queue, Retry


class RqQueueClient:
    def __init__(self, redis_url: str, queue_name: str) -> None:
        self.redis = Redis.from_url(redis_url)
        self.queue = Queue(queue_name, connection=self.redis)

    def enqueue_ingestion(self, document_id: str, collection: str) -> str:
        job = self.queue.enqueue(
            "app.workers.ingest_worker.ingest_document_job",
            document_id,
            collection,
            retry=Retry(max=3, interval=[10, 30, 60]),
            job_timeout="30m",
            failure_ttl=86400,
        )
        return job.id
