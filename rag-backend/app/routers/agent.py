import threading

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import get_llm_semaphore, get_rag_query_service
from app.errors import RetryableIngestionError, ValidationError
from app.sanitization import sanitize_error_message
from app.services.rag_query_service import RagQueryService


router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRunRequest(BaseModel):
    prompt: str = Field(min_length=1)
    agent_id: str = Field(default="research-agent", alias="agentId")
    thread_id: str | None = Field(default=None, alias="threadId")
    vector_provider: str = Field(default="chroma", alias="vectorProvider")
    collection: str = "default"
    debug: bool = True


class AgentRunV2Request(AgentRunRequest):
    pass


@router.post("/run")
def run_agent(
    request: AgentRunRequest,
    rag_query_service: RagQueryService = Depends(get_rag_query_service),
    semaphore: threading.Semaphore = Depends(get_llm_semaphore),
) -> dict:
    if not semaphore.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="服务繁忙，请稍后重试")
    try:
        return rag_query_service.run(
            prompt=request.prompt,
            collection=request.collection,
            agent_id=request.agent_id,
            thread_id=request.thread_id,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RetryableIngestionError as exc:
        raise HTTPException(status_code=429, detail="服务繁忙，请稍后重试")
    except Exception as exc:
        detail = sanitize_error_message(str(exc))
        raise HTTPException(status_code=500, detail=f"RAG query failed: {detail}") from exc
    finally:
        semaphore.release()


@router.post("/run_v2")
def run_agent_v2(
    request: AgentRunV2Request,
    rag_query_service: RagQueryService = Depends(get_rag_query_service),
    semaphore: threading.Semaphore = Depends(get_llm_semaphore),
) -> dict:
    """Hybrid retrieval (BM25 + vector + RRF + CrossEncoder)."""
    if not semaphore.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="服务繁忙，请稍后重试")
    try:
        return rag_query_service.run(
            prompt=request.prompt,
            collection=request.collection,
            agent_id=request.agent_id,
            thread_id=request.thread_id,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RetryableIngestionError as exc:
        raise HTTPException(status_code=429, detail="服务繁忙，请稍后重试")
    except Exception as exc:
        detail = sanitize_error_message(str(exc))
        raise HTTPException(status_code=500, detail=f"RAG query failed: {detail}") from exc
    finally:
        semaphore.release()
