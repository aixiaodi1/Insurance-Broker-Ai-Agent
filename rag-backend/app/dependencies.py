import threading
from functools import lru_cache

from app.config import Settings
from app.observability import get_logger
from app.config import get_settings as get_config_settings
logger = get_logger(__name__)

from app.infrastructure.chunkers.base import Chunker
from app.infrastructure.chunkers.document_aware import DocumentAwareChunker
from app.infrastructure.embeddings.base import EmbeddingProvider
from app.infrastructure.embeddings.local_api import LocalApiEmbeddingProvider
from app.infrastructure.embeddings.sentence_transformers import SentenceTransformersEmbeddingProvider
from app.infrastructure.generators.base import AnswerGenerator
from app.infrastructure.generators.minimax import MiniMaxGenerator
from app.infrastructure.parsers.base import DocumentParser
from app.infrastructure.parsers.quality_gate import ParseQualityGate
from app.infrastructure.parsers.router import ParserRouter
from app.infrastructure.queue.base import QueueClient
from app.infrastructure.queue.rq_queue import RqQueueClient
from app.infrastructure.rerankers.base import Reranker
from app.infrastructure.rerankers.local_api import LocalApiReranker
from app.infrastructure.repositories.base import Repository
from app.infrastructure.repositories.sqlite import SQLiteRepository
from app.infrastructure.vectorstores.base import VectorStore
from app.infrastructure.vectorstores.chroma_store import ChromaVectorStore
from app.retrieval.bm25_indexer import MemoryBM25Indexer
from app.services.document_service import DocumentService
from app.services.ingestion_service import IngestionService
from app.services.job_service import JobService
from app.services.rag_query_service import RagQueryService
from app.services.thread_state_store import ThreadStateStore

app_state: dict = {}


def set_app_state(state: dict) -> None:
    app_state.clear()
    app_state.update(state)


def get_cross_encoder():
    return app_state.get("cross_encoder")


def get_bm25_indexer() -> MemoryBM25Indexer | None:
    return app_state.get("bm25_indexer")


def get_settings() -> Settings:
    return get_config_settings()


@lru_cache
def get_repository() -> Repository:
    settings = get_settings()
    repository = SQLiteRepository(settings.database_url)
    repository.initialize()
    return repository


@lru_cache
def get_parser_registry() -> ParserRouter:
    return ParserRouter.default()


@lru_cache
def get_chunker() -> Chunker:
    settings = get_settings()
    return DocumentAwareChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )


@lru_cache
def get_embedder() -> EmbeddingProvider:
    settings = get_settings()
    embedder = build_embedder(settings)
    try:
        embedder.embed_texts(["health check"])
    except Exception:
        logger.warning("Embedding API 不可用，请检查服务是否已启动")
    return embedder


_llm_semaphore = threading.Semaphore(5)


def get_llm_semaphore() -> threading.Semaphore:
    return _llm_semaphore


def build_embedder(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider.lower() in {"api", "local-api", "http"}:
        return LocalApiEmbeddingProvider(
            base_url=settings.embedding_api_base_url,
            path=settings.embedding_api_path,
            api_key=settings.embedding_api_key or settings.minimax_api_key,
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
            batch_size=settings.embedding_batch_size,
        )

    preloaded = app_state.get("embedding_model")
    return SentenceTransformersEmbeddingProvider(
        model_name=settings.embedding_model,
        batch_size=settings.embedding_batch_size,
        model=preloaded,
    )


@lru_cache
def get_vector_store() -> VectorStore:
    settings = get_settings()
    return ChromaVectorStore(settings.chroma_persist_dir)


@lru_cache
def get_reranker() -> Reranker:
    settings = get_settings()
    return LocalApiReranker(
        base_url=settings.rerank_api_base_url,
        path=settings.rerank_api_path,
        model=settings.rerank_model,
        top_k=settings.rag_rerank_top_k,
    )


@lru_cache
def get_answer_generator() -> AnswerGenerator:
    settings = get_settings()
    return MiniMaxGenerator(
        base_url=settings.llm_api_base_url,
        path=settings.llm_api_path,
        api_key=settings.llm_api_key or settings.minimax_api_key,
        model=settings.llm_model,
    )


@lru_cache
def get_queue_client() -> QueueClient:
    settings = get_settings()
    return RqQueueClient(
        redis_url=settings.redis_url,
        queue_name=settings.rq_queue_name,
    )


def get_job_service() -> JobService:
    return JobService(get_repository())


def get_document_service() -> DocumentService:
    return DocumentService(
        repository=get_repository(),
        job_service=get_job_service(),
        queue_client=get_queue_client(),
        settings=get_settings(),
    )


def get_ingestion_service() -> IngestionService:
    return IngestionService(
        repository=get_repository(),
        job_service=get_job_service(),
        parser=get_parser_registry(),
        chunker=get_chunker(),
        embedding_provider=get_embedder(),
        vector_store=get_vector_store(),
        bm25_indexer=get_bm25_indexer(),
        quality_gate=ParseQualityGate(),
    )


@lru_cache
def get_thread_state_store() -> ThreadStateStore:
    settings = get_settings()
    return ThreadStateStore(settings.redis_url)


def get_rag_query_service() -> RagQueryService:
    settings = get_settings()
    cross_encoder = get_cross_encoder()
    bm25_indexer = get_bm25_indexer()
    state_store = get_thread_state_store()
    if bm25_indexer is not None:
        return RagQueryService(
            embedder=get_embedder(),
            vector_store=get_vector_store(),
            generator=get_answer_generator(),
            repository=get_repository(),
            cross_encoder=cross_encoder,
            reranker=get_reranker() if cross_encoder is None else None,
            bm25_indexer=bm25_indexer,
            llm_provider=settings.llm_provider,
            retrieval_top_k=min(settings.rag_retrieval_top_k, 10) if cross_encoder else settings.rag_retrieval_top_k,
            rerank_top_k=3 if cross_encoder else settings.rag_rerank_top_k,
            embedding_dimension=settings.embedding_dimension,
            state_store=state_store,
            redis_url=settings.redis_url,
        )
    return RagQueryService(
        embedder=get_embedder(),
        vector_store=get_vector_store(),
        reranker=get_reranker(),
        generator=get_answer_generator(),
        llm_provider=settings.llm_provider,
        retrieval_top_k=settings.rag_retrieval_top_k,
        rerank_top_k=settings.rag_rerank_top_k,
        embedding_dimension=settings.embedding_dimension,
        state_store=state_store,
        redis_url=settings.redis_url,
    )


def close_cached_dependencies() -> None:
    if get_vector_store.cache_info().currsize:
        vector_store = get_vector_store()
        close = getattr(vector_store, "close", None)
        if callable(close):
            close()

    get_repository.cache_clear()
    get_parser_registry.cache_clear()
    get_chunker.cache_clear()
    get_embedder.cache_clear()
    get_vector_store.cache_clear()
    get_reranker.cache_clear()
    get_answer_generator.cache_clear()
    get_queue_client.cache_clear()
    if hasattr(get_config_settings, "cache_clear"):
        get_config_settings.cache_clear()
