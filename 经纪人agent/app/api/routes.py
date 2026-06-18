import json
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse
from typing import Literal

from app.agents.transparent_runtime import TransparentAgentRuntime
from app.agents.run_control import RunControlStore
from app.config import PROJECT_ROOT, settings
from app.memory.hermes import HermesMemoryStore
from app.memory.llm import build_memory_extractor_from_settings
from app.memory.sqlite_memory import SQLiteMemory
from app.web_acquisition.schemas import StrategyName
from app.web_acquisition.service import WebAcquisitionService
from app.web_acquisition.storage import SQLiteAcquisitionStore


router = APIRouter()


class ResearchRequest(BaseModel):
    user_id: str
    message: str
    thread_id: str | None = None


class RunControlRequest(BaseModel):
    action: Literal["interrupt"]


class RunGuidanceRequest(BaseModel):
    content: str
    priority: Literal["normal", "immediate"] = "normal"


class MemoryActionRequest(BaseModel):
    target: Literal["memory", "user"]
    action: Literal["add", "replace", "remove"]
    content: str | None = None
    old_text: str | None = None


class WebAcquisitionRunRequest(BaseModel):
    url: str
    goal: str
    allowed_domains: list[str] | None = None
    strategy: StrategyName = "auto"
    max_steps: int = 20
    timeout_seconds: int = 90


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def build_web_acquisition_service() -> WebAcquisitionService:
    return WebAcquisitionService(storage=_web_acquisition_store())


def _web_acquisition_store() -> SQLiteAcquisitionStore:
    store = SQLiteAcquisitionStore(settings.web_acquisition_db_path)
    store.init_schema()
    return store


def _run_control_store() -> RunControlStore:
    store = RunControlStore(settings.memory_db_path)
    store.init_schema()
    return store


@router.post("/agent/runs/{run_id}/control")
def control_agent_run(run_id: str, request: RunControlRequest) -> dict:
    store = _run_control_store()
    if not store.request_interrupt(run_id):
        raise HTTPException(status_code=404, detail="Agent run not found")
    return {"run_id": run_id, "action": request.action, "status": "requested"}


@router.put("/agent/runs/{run_id}/guidance")
def upsert_agent_guidance(run_id: str, request: RunGuidanceRequest) -> dict:
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Guidance content is required")
    guidance = _run_control_store().upsert_guidance(run_id, content, request.priority)
    if guidance is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return {"run_id": run_id, "guidance": guidance}


@router.delete("/agent/runs/{run_id}/guidance")
def delete_agent_guidance(run_id: str) -> dict:
    store = _run_control_store()
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return {"run_id": run_id, "deleted": store.delete_guidance(run_id)}


@router.post("/web-acquisition/run")
async def run_web_acquisition(request: WebAcquisitionRunRequest) -> dict:
    service = build_web_acquisition_service()
    response = await service.acquire(
        url=request.url,
        goal=request.goal,
        allowed_domains=request.allowed_domains,
        strategy=request.strategy,
        max_steps=request.max_steps,
        timeout_seconds=request.timeout_seconds,
    )
    return {
        "task_id": response["task_id"],
        "status": response["status"],
        "result": asdict(response["result"]),
    }


@router.get("/web-acquisition/tasks/{task_id}")
def get_web_acquisition_task(task_id: str) -> dict:
    task = _web_acquisition_store().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Web acquisition task not found")
    return task


@router.get("/web-acquisition/tasks/{task_id}/steps")
def get_web_acquisition_steps(task_id: str) -> dict:
    store = _web_acquisition_store()
    if store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Web acquisition task not found")
    return {"task_id": task_id, "steps": store.list_steps(task_id)}


@router.get("/web-acquisition/tasks/{task_id}/files")
def get_web_acquisition_files(task_id: str) -> dict:
    store = _web_acquisition_store()
    if store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Web acquisition task not found")
    return {"task_id": task_id, "files": store.list_files(task_id)}


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

        runtime = TransparentAgentRuntime(
            llm_client=llm_client,
            project_root=PROJECT_ROOT,
            control_store=_run_control_store(),
        )
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

    runtime = TransparentAgentRuntime(
        llm_client=llm_client,
        project_root=PROJECT_ROOT,
        control_store=_run_control_store(),
    )
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
        if event.get("type") in {
            "goal_anchored",
            "plan_updated",
            "action_started",
            "action_completed",
            "recovery_started",
            "guidance_applied",
            "interrupt_requested",
            "run_interrupted",
        }:
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
