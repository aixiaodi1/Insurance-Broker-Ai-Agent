import json

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.responses import StreamingResponse
from typing import Literal

from app.agents.transparent_runtime import TransparentAgentRuntime
from app.config import PROJECT_ROOT, settings
from app.memory.hermes import HermesMemoryStore
from app.memory.llm import build_memory_extractor_from_settings
from app.memory.sqlite_memory import SQLiteMemory


router = APIRouter()


class ResearchRequest(BaseModel):
    user_id: str
    message: str
    thread_id: str | None = None


class MemoryActionRequest(BaseModel):
    target: Literal["memory", "user"]
    action: Literal["add", "replace", "remove"]
    content: str | None = None
    old_text: str | None = None


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/agent/research")
def research(request: ResearchRequest) -> dict:
    return _run_transparent_research(request)


@router.post("/agent/research/stream")
def research_stream(request: ResearchRequest) -> StreamingResponse:
    llm_client = build_memory_extractor_from_settings(settings)

    def iter_events():
        if llm_client is None:
            yield json.dumps(
                {
                    "type": "error",
                    "summary": "LLM is not configured; transparent ReAct runtime cannot start.",
                },
                ensure_ascii=False,
            ) + "\n"
            return

        runtime = TransparentAgentRuntime(llm_client=llm_client, project_root=PROJECT_ROOT)
        for event in runtime.stream(
            request.message,
            thread_id=request.thread_id,
            user_id=request.user_id,
        ):
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(iter_events(), media_type="application/x-ndjson")


def _run_transparent_research(request: ResearchRequest) -> dict:
    thread_id = request.thread_id or f"{request.user_id}:transparent"
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    session_id = memory.create_session(
        user_id=request.user_id,
        thread_id=thread_id,
        title=request.message[:40] or "transparent agent run",
        task_type="transparent_react",
    )
    memory.add_message(session_id=session_id, role="user", content=request.message)

    llm_client = build_memory_extractor_from_settings(settings)
    if llm_client is None:
        final_summary = "LLM is not configured; transparent ReAct runtime cannot start."
        memory.add_message(session_id=session_id, role="assistant", content=final_summary)
        return {
            "run_id": session_id,
            "thread_id": thread_id,
            "task_type": "transparent_react",
            "final_summary": final_summary,
            "evidence_score": None,
            "stop_reasons": [{"code": "llm_not_configured", "message": final_summary}],
            "user_visible_steps": [],
            "rag_citations": [],
            "audit_run_id": session_id,
            "workflow_trace": [{"type": "error", "summary": final_summary}],
            "memory_snapshot": None,
            "remembered_context": {},
            "memory_citations": [],
        }

    runtime = TransparentAgentRuntime(llm_client=llm_client, project_root=PROJECT_ROOT)
    events = list(runtime.stream(request.message, thread_id=thread_id, user_id=request.user_id))
    final_summary = _final_summary_from_events(events)
    run_id = _run_id_from_events(events) or session_id
    if final_summary:
        memory.add_message(session_id=session_id, role="assistant", content=final_summary)
    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "task_type": "transparent_react",
        "final_summary": final_summary,
        "evidence_score": None,
        "stop_reasons": [],
        "user_visible_steps": _visible_steps_from_events(events),
        "rag_citations": [],
        "audit_run_id": run_id,
        "workflow_trace": events,
        "memory_snapshot": None,
        "remembered_context": {},
        "memory_citations": [],
    }


def _final_summary_from_events(events: list[dict]) -> str:
    for event in reversed(events):
        if event.get("type") == "final_answer":
            return str(event.get("finalAnswer") or event.get("summary") or "")
    return ""


def _run_id_from_events(events: list[dict]) -> str | None:
    for event in events:
        run_id = event.get("run_id")
        if isinstance(run_id, str):
            return run_id
    return None


def _visible_steps_from_events(events: list[dict]) -> list[dict]:
    visible = []
    for event in events:
        if event.get("type") in {"intent_anchor", "task_decomposition", "tool_boundary", "tool_started", "tool_finished", "observation"}:
            visible.append(
                {
                    "type": event.get("type"),
                    "title": event.get("type"),
                    "detail": event.get("summary", ""),
                }
            )
    return visible


@router.get("/agent/memory/search")
def search_memory(q: str | None = None, session_id: str | None = None, limit: int = 10, offset: int = 0) -> dict:
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    if session_id is not None:
        return {"results": memory.get_session_messages(session_id=session_id, limit=limit, offset=offset)}
    if q is not None:
        return {"results": memory.search_messages(q, limit=limit)}
    return {"results": memory.list_sessions(limit=limit)}


@router.get("/agent/memory/snapshot")
def memory_snapshot() -> dict:
    hermes_memory = HermesMemoryStore(
        settings.hermes_memory_dir,
        memory_char_limit=settings.hermes_memory_char_limit,
        user_char_limit=settings.hermes_user_char_limit,
    )
    return {
        "snapshot": hermes_memory.render_snapshot(),
        "memory": hermes_memory.stats("memory"),
        "user": hermes_memory.stats("user"),
    }


@router.get("/agent/memory/facts")
def memory_facts(user_id: str, limit: int = 20) -> dict:
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    return {"results": memory.list_memory_facts(f"user:{user_id}:", limit=limit)}


@router.delete("/agent/memory/facts/{fact_id}")
def delete_memory_fact(fact_id: str) -> dict:
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    return {"deleted": memory.delete_memory_fact(fact_id)}


@router.get("/agent/memory/project")
def project_memory(q: str, limit: int = 10) -> dict:
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    return {"results": memory.search_project_memory(q, limit=limit)}


@router.get("/agent/memory/evidence")
def evidence_memory(q: str, limit: int = 10) -> dict:
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    return {"results": memory.search_evidence_memory(q, limit=limit)}


@router.get("/agent/memory/tool-events")
def tool_events(q: str, limit: int = 20) -> dict:
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    return {"results": memory.search_tool_events(q, limit=limit)}


@router.get("/agent/memory/export")
def export_session_memory(session_id: str) -> dict:
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    return {"session_id": session_id, "jsonl": memory.export_session_jsonl(session_id)}


@router.post("/agent/memory")
def manage_memory(request: MemoryActionRequest) -> dict:
    hermes_memory = HermesMemoryStore(
        settings.hermes_memory_dir,
        memory_char_limit=settings.hermes_memory_char_limit,
        user_char_limit=settings.hermes_user_char_limit,
    )
    if request.action == "remove":
        if request.old_text is None:
            return {"success": False, "error": "old_text is required for remove"}
        result = hermes_memory.remove(request.target, request.old_text)
    elif request.action == "replace":
        if request.old_text is None or request.content is None:
            return {"success": False, "error": "old_text and content are required for replace"}
        result = hermes_memory.replace(request.target, request.old_text, request.content)
    else:
        if request.content is None:
            return {"success": False, "error": "content is required for add"}
        result = hermes_memory.add(request.target, request.content)
    return {
        "result": result,
        "snapshot": hermes_memory.render_snapshot(),
    }
