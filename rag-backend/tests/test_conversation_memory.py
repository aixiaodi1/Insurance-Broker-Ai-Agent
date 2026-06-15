import sqlite3
from pathlib import Path

from app.infrastructure.repositories.sqlite import SQLiteRepository
from app.services.conversation_memory import ConversationMemoryStore


def test_conversation_memory_uses_same_sqlite_file_as_rag_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "rag.sqlite"
    database_url = f"sqlite:///{database_path}"
    repository = SQLiteRepository(database_url)
    repository.initialize()

    memory = ConversationMemoryStore(database_url)
    memory.initialize()
    session_id = memory.create_session(
        user_id="user-1",
        thread_id="thread-1",
        title="first turn",
        task_type="conversation",
    )
    memory.add_message(session_id=session_id, role="user", content="research product alpha")

    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'virtual table')"
            ).fetchall()
        }

    assert "documents" in table_names
    assert "chunks" in table_names
    assert "sessions" in table_names
    assert "messages" in table_names
    assert "messages_fts" in table_names
    assert memory.get_recent_thread_messages("user-1", "thread-1")[0]["content"] == "research product alpha"


def test_conversation_memory_recalls_thread_summary_and_recent_messages(tmp_path: Path) -> None:
    memory = ConversationMemoryStore(f"sqlite:///{tmp_path / 'rag.sqlite'}")
    memory.initialize()
    session_id = memory.create_session(
        user_id="user-1",
        thread_id="thread-1",
        title="alpha",
        task_type="conversation",
    )
    memory.add_message(session_id=session_id, role="user", content="Product Alpha waiting period")
    memory.add_message(session_id=session_id, role="assistant", content="Product Alpha waiting period is 90 days")
    memory.upsert_thread_summary(
        user_id="user-1",
        thread_id="thread-1",
        summary="Product Alpha waiting period: 90 days",
        latest_session_id=session_id,
        final_answer="Product Alpha waiting period is 90 days",
    )

    remembered = memory.recall_memory(
        user_id="user-1",
        thread_id="thread-1",
        query="continue previous waiting period",
    )

    assert remembered["thread_summary"]["summary"] == "Product Alpha waiting period: 90 days"
    assert remembered["recent_messages"][-1]["content"] == "Product Alpha waiting period is 90 days"
    assert remembered["citations"][0]["source"] == "thread_summary"
