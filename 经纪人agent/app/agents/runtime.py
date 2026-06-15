from uuid import uuid4

from app.agents.direct_responses import generate_direct_response
from app.agents.graphs.research_graph import run_research_graph
from app.agents.nodes.memory_nodes import load_thread_memory, save_memory_and_audit
from app.agents.routing import route_user_intent
from app.agents.state import new_agent_state
from app.audit.logger import AuditLogger
from app.config import settings
from app.memory.hermes import HermesMemoryStore
from app.memory.learning import capture_memory_entries
from app.memory.llm import build_memory_extractor_from_settings
from app.memory.sqlite_memory import SQLiteMemory


def run_research_task(user_id: str, message: str, thread_id: str | None = None) -> dict:
    effective_thread_id = thread_id or f"{user_id}:{uuid4()}"
    hermes_memory = HermesMemoryStore(
        settings.hermes_memory_dir,
        memory_char_limit=settings.hermes_memory_char_limit,
        user_char_limit=settings.hermes_user_char_limit,
    )
    memory = SQLiteMemory(settings.memory_db_path)
    memory.init_schema()
    logger = AuditLogger(memory=memory, runs_dir=settings.runs_dir)

    state = new_agent_state(user_id=user_id, user_input=message, thread_id=effective_thread_id)
    state["thread_id_provided"] = thread_id is not None
    state["memory_snapshot"] = hermes_memory.render_snapshot()
    memory_extractor = build_memory_extractor_from_settings(settings)
    state = route_user_intent(state, router_model=memory_extractor)
    _log_stage(
        logger,
        state,
        "runtime_router",
        "route_user_intent",
        {"message": message, "thread_id_provided": state["thread_id_provided"]},
        {"task_type": state.get("task_type"), "reason": state.get("route_reason")},
    )

    if state.get("task_type") == "official_evidence_research":
        state = run_research_graph(
            state,
            memory=memory,
            memory_extractor=memory_extractor,
        )

        _log_stage(logger, state, "load_thread_memory", "memory_recall", {"message": message}, {"citations": len(state.get("memory_citations", []))})
        _log_stage(logger, state, "novice_intake", "run_intake_graph", {"message": message}, {"product_name": state.get("product_name")})
        _log_stage(
            logger,
            state,
            "local_evidence_search",
            "run_evidence_graph",
            {"product_name": state.get("product_name")},
            {"local_candidates": len(state.get("local_candidates", []))},
        )
        _log_stage(
            logger,
            state,
            "rag_citation_check",
            "rag_search",
            {"product_name": state.get("product_name")},
            {"citations": len(state.get("rag_citations", []))},
        )
        _log_stage(
            logger,
            state,
            "save_memory_and_audit",
            "save_memory_and_audit",
            {"session_id": state.get("session_id")},
            {"has_thread_summary": bool((state.get("remembered_context") or {}).get("thread_summary"))},
        )
        _log_stage(
            logger,
            state,
            "generate_user_friendly_summary",
            "run_report_graph",
            {"score": state.get("evidence_score")},
            {"has_final_summary": bool(state.get("final_summary"))},
        )
    else:
        state = load_thread_memory(state, memory)
        _log_stage(logger, state, "load_thread_memory", "memory_recall", {"message": message}, {"citations": len(state.get("memory_citations", []))})
        state = generate_direct_response(state)
        _log_stage(
            logger,
            state,
            "direct_response",
            "generate_direct_response",
            {"task_type": state.get("task_type")},
            {"has_final_summary": bool(state.get("final_summary"))},
        )
        state = save_memory_and_audit(state, memory, memory_extractor=memory_extractor)
        _log_stage(
            logger,
            state,
            "save_memory_and_audit",
            "save_memory_and_audit",
            {"session_id": state.get("session_id")},
            {"has_thread_summary": bool((state.get("remembered_context") or {}).get("thread_summary"))},
        )

    if state.get("final_summary"):
        for target, content in capture_memory_entries(message, state["final_summary"]):
            hermes_memory.add(target, content)
        state["memory_snapshot"] = hermes_memory.render_snapshot()
    return state


def _log_stage(
    logger: AuditLogger,
    state: dict,
    node: str,
    tool: str,
    input_json: dict,
    output_json: dict,
) -> None:
    logger.log_tool_event(
        run_id=state["run_id"],
        thread_id=state["thread_id"],
        node=node,
        tool=tool,
        status="success",
        input_json=input_json,
        output_json=output_json,
    )
    state["tool_events"].append(
        {
            "node": node,
            "tool": tool,
            "status": "success",
            "input_summary": input_json,
            "output_summary": output_json,
        }
    )
