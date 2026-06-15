import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4


class ConversationMemoryStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.database_path = Path(database_url.removeprefix("sqlite:///"))

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    score REAL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reasoning TEXT,
                    tool_calls TEXT,
                    token_count INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    session_id UNINDEXED,
                    message_id UNINDEXED
                );

                CREATE TABLE IF NOT EXISTS thread_summaries (
                    thread_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    latest_session_id TEXT,
                    final_answer TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_facts (
                    id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source_session_id TEXT,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(namespace, key)
                );

                CREATE TABLE IF NOT EXISTS project_memory (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source_session_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(kind, key)
                );

                CREATE TABLE IF NOT EXISTS evidence_memory (
                    id TEXT PRIMARY KEY,
                    product_name TEXT,
                    title TEXT NOT NULL,
                    source_url TEXT,
                    source_tier TEXT NOT NULL,
                    chunk_id TEXT,
                    file_hash TEXT,
                    source_session_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def create_session(self, user_id: str, thread_id: str, title: str, task_type: str) -> str:
        session_id = f"session_{uuid4().hex}"
        now = self._now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO sessions (id, user_id, thread_id, title, task_type, started_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, user_id, thread_id, title, task_type, now, now),
            )
        return session_id

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        reasoning: str | None = None,
        tool_calls: list[dict] | None = None,
        token_count: int | None = None,
    ) -> str:
        message_id = f"message_{uuid4().hex}"
        now = self._now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO messages (id, session_id, role, content, reasoning, tool_calls, token_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    role,
                    content,
                    reasoning,
                    json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    token_count,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO messages_fts (content, session_id, message_id) VALUES (?, ?, ?)",
                (content, session_id, message_id),
            )
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
        return message_id

    def get_recent_thread_messages(self, user_id: str, thread_id: str, limit: int = 6) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.id, m.session_id, m.role, m.content, m.created_at
                FROM messages AS m
                JOIN sessions AS s ON s.id = m.session_id
                WHERE s.user_id = ? AND s.thread_id = ?
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (user_id, thread_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def upsert_thread_summary(
        self,
        user_id: str,
        thread_id: str,
        summary: str,
        latest_session_id: str,
        final_answer: str | None,
    ) -> None:
        now = self._now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO thread_summaries (
                    thread_id, user_id, summary, latest_session_id, final_answer, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    summary = excluded.summary,
                    latest_session_id = excluded.latest_session_id,
                    final_answer = excluded.final_answer,
                    updated_at = excluded.updated_at
                """,
                (thread_id, user_id, summary, latest_session_id, final_answer, now, now),
            )

    def get_thread_summary(self, thread_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT thread_id, user_id, summary, latest_session_id, final_answer, created_at, updated_at
                FROM thread_summaries
                WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        if not query.strip():
            return []
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.id, m.session_id, m.role, m.content, m.created_at
                FROM messages_fts
                JOIN messages AS m ON m.id = messages_fts.message_id
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def recall_memory(self, user_id: str, thread_id: str, query: str, limit: int = 6) -> dict:
        thread_summary = self.get_thread_summary(thread_id)
        recent_messages = self.get_recent_thread_messages(user_id, thread_id, limit=limit)
        try:
            messages = self.search_messages(query, limit=limit)
        except sqlite3.OperationalError:
            messages = []

        citations = []
        if thread_summary:
            citations.append(
                {
                    "source": "thread_summary",
                    "id": thread_summary["thread_id"],
                    "label": "thread summary",
                }
            )
        citations.extend(
            {"source": "message", "id": item["id"], "label": item["role"]}
            for item in messages
        )
        return {
            "thread_summary": thread_summary,
            "recent_messages": recent_messages,
            "messages": messages,
            "citations": citations,
        }

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat()
