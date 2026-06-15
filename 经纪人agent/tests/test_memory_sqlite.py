from app.memory.sqlite_memory import SQLiteMemory


def test_memory_stores_raw_message_and_searches_with_fts(tmp_path):
    db_path = tmp_path / "memory.sqlite3"
    memory = SQLiteMemory(db_path)
    memory.init_schema()
    session_id = memory.create_session(
        user_id="user-1",
        thread_id="user-1:task-1",
        title="众民保研究",
        task_type="product_research",
    )
    memory.add_message(session_id=session_id, role="user", content="帮我查众民保的官方资料")
    results = memory.search_messages("众民保")
    assert len(results) == 1
    assert results[0]["content"] == "帮我查众民保的官方资料"


def test_audit_logger_writes_tool_event_to_db_and_jsonl(tmp_path):
    from app.audit.logger import AuditLogger

    memory = SQLiteMemory(tmp_path / "memory.sqlite3")
    memory.init_schema()
    logger = AuditLogger(memory=memory, runs_dir=tmp_path / "runs")
    logger.log_tool_event(
        run_id="run-1",
        thread_id="user-1:task-1",
        node="local_evidence_search",
        tool="search_local_specs",
        status="success",
        input_json={"query": "众民保"},
        output_json={"count": 1},
    )
    events_file = tmp_path / "runs" / "run-1" / "events.jsonl"
    assert events_file.exists()
    assert "search_local_specs" in events_file.read_text(encoding="utf-8")
