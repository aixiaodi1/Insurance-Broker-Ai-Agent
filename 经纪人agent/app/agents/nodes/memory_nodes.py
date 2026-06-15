from __future__ import annotations

from app.memory.extraction import MemoryExtractor, extract_memory_payload
from app.memory.sqlite_memory import SQLiteMemory


def load_thread_memory(state: dict, memory: SQLiteMemory) -> dict:
    remembered_context = memory.recall_memory(
        user_id=state["user_id"],
        thread_id=state["thread_id"],
        query=state.get("user_input", ""),
    )
    state["remembered_context"] = remembered_context
    state["memory_citations"] = remembered_context.get("citations", [])
    thread_summary = remembered_context.get("thread_summary")
    if thread_summary:
        state["conversation_summary"] = _append_summary(
            state.get("conversation_summary"),
            thread_summary.get("summary", ""),
        )
    recent_messages = memory.get_recent_thread_messages(
        user_id=state["user_id"],
        thread_id=state["thread_id"],
        limit=6,
    )
    if recent_messages:
        current_messages = list(state.get("messages", []))
        state["messages"] = [
            {"role": item["role"], "content": item["content"]}
            for item in recent_messages
        ] + current_messages

    if not state.get("session_id"):
        session_id = memory.create_session(
            user_id=state["user_id"],
            thread_id=state["thread_id"],
            title=(state.get("user_input") or "")[:40] or "insurance product research",
            task_type=state.get("task_type") or "official_evidence_research",
        )
        state["session_id"] = session_id
        memory.add_message(session_id=session_id, role="user", content=state.get("user_input", ""))

    return state


def _append_summary(existing: str | None, summary: str) -> str | None:
    if not summary:
        return existing
    if existing:
        return f"{existing}\nThread memory: {summary}"
    return f"Thread memory: {summary}"


def save_memory_and_audit(
    state: dict,
    memory: SQLiteMemory,
    memory_extractor: MemoryExtractor | None = None,
) -> dict:
    session_id = state.get("session_id")
    if not session_id:
        return state

    final_summary = state.get("final_summary")
    if final_summary and not state.get("assistant_message_saved"):
        memory.add_message(session_id=session_id, role="assistant", content=final_summary)
        state["assistant_message_saved"] = True

    memory.upsert_thread_summary(
        user_id=state["user_id"],
        thread_id=state["thread_id"],
        summary=_summarize_thread_state(state),
        latest_session_id=session_id,
        final_summary=final_summary,
    )
    _save_structured_memory(memory, state, session_id)
    _save_extracted_memory(memory, state, session_id, memory_extractor)
    return state


def _summarize_thread_state(state: dict) -> str:
    if state.get("task_type") != "official_evidence_research":
        return f"Task: {state.get('task_type')}; latest_answer: {(state.get('final_summary') or '')[:120]}"
    product = state.get("product_name") or "unknown product"
    score = (state.get("evidence_score") or {}).get("total", 0)
    reasons = state.get("stop_reasons") or []
    reason_text = "; ".join(item.get("code", "") for item in reasons if item.get("code")) or "no stop reason"
    return f"Product: {product}; evidence_score: {score}; status: {reason_text}"


def _save_structured_memory(memory: SQLiteMemory, state: dict, session_id: str) -> None:
    user_id = state.get("user_id")
    if user_id:
        memory.upsert_memory_fact(
            namespace=f"user:{user_id}:profile",
            key="user_level",
            value={"value": state.get("user_level", "novice")},
            source_session_id=session_id,
            confidence=1.0,
        )

    product_name = state.get("product_name")
    if product_name:
        memory.upsert_project_memory(
            kind="product_alias",
            key=product_name,
            value={
                "product_name": product_name,
                "aliases": state.get("aliases", []),
            },
            source_session_id=session_id,
        )

    for item in state.get("rag_citations", []) or []:
        memory.upsert_evidence_memory(
            product_name=item.get("product_name") or product_name,
            title=item.get("title") or "Untitled evidence",
            source_url=item.get("source_url"),
            source_tier=item.get("source_tier", "S5"),
            chunk_id=item.get("chunk_id"),
            file_hash=item.get("file_hash"),
            source_session_id=session_id,
        )


def _save_extracted_memory(
    memory: SQLiteMemory,
    state: dict,
    session_id: str,
    memory_extractor: MemoryExtractor | None,
) -> None:
    if memory_extractor is None:
        state["memory_extraction"] = {"ok": False, "skipped": True, "error": "memory extractor not configured"}
        return

    extraction = extract_memory_payload(
        user_input=state.get("user_input", ""),
        final_summary=state.get("final_summary"),
        extractor=memory_extractor,
    )
    state["memory_extraction"] = extraction
    if not extraction.get("ok"):
        return

    for item in extraction.get("facts", []):
        namespace = item.get("namespace")
        key = item.get("key")
        value = item.get("value")
        if isinstance(namespace, str) and isinstance(key, str) and isinstance(value, dict):
            memory.upsert_memory_fact(
                namespace=namespace,
                key=key,
                value=value,
                source_session_id=session_id,
                confidence=float(item.get("confidence") or 1.0),
            )

    for item in extraction.get("project_memories", []):
        kind = item.get("kind")
        key = item.get("key")
        value = item.get("value")
        if isinstance(kind, str) and isinstance(key, str) and isinstance(value, dict):
            memory.upsert_project_memory(
                kind=kind,
                key=key,
                value=value,
                source_session_id=session_id,
            )

    for item in extraction.get("evidence_memories", []):
        title = item.get("title")
        if isinstance(title, str):
            memory.upsert_evidence_memory(
                product_name=item.get("product_name"),
                title=title,
                source_url=item.get("source_url"),
                source_tier=item.get("source_tier", "S5"),
                chunk_id=item.get("chunk_id"),
                file_hash=item.get("file_hash"),
                source_session_id=session_id,
            )
