from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4


class SQLiteMemory:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'running',
                    score REAL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    reasoning TEXT,
                    tool_calls TEXT DEFAULT '[]',
                    token_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    session_id UNINDEXED,
                    message_id UNINDEXED,
                    tokenize='trigram'
                );

                CREATE TABLE IF NOT EXISTS tool_events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    node TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    input_json TEXT DEFAULT '{}',
                    output_json TEXT DEFAULT '{}',
                    url TEXT,
                    file_path TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS thread_summaries (
                    thread_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    latest_session_id TEXT,
                    final_summary TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS memory_facts (
                    id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source_session_id TEXT,
                    confidence REAL DEFAULT 1.0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(namespace, key)
                );

                CREATE TABLE IF NOT EXISTS project_memory (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source_session_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(kind, key)
                );

                CREATE TABLE IF NOT EXISTS evidence_memory (
                    id TEXT PRIMARY KEY,
                    product_name TEXT,
                    title TEXT NOT NULL,
                    source_url TEXT,
                    source_tier TEXT DEFAULT 'S5',
                    chunk_id TEXT,
                    file_hash TEXT,
                    source_session_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_url, chunk_id, file_hash)
                );
                """
            )

    def create_session(self, user_id: str, thread_id: str, title: str, task_type: str) -> str:
        session_id = str(uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, thread_id, title, task_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, user_id, thread_id, title, task_type),
            )
        return session_id

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        reasoning: str | None = None,
        tool_calls: list[dict] | None = None,
        token_count: int = 0,
    ) -> str:
        message_id = str(uuid4())
        tool_calls_json = json.dumps(tool_calls or [], ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (id, session_id, role, content, reasoning, tool_calls, token_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, reasoning, tool_calls_json, token_count),
            )
            conn.execute(
                """
                INSERT INTO messages_fts (content, session_id, message_id)
                VALUES (?, ?, ?)
                """,
                (content, session_id, message_id),
            )
            conn.execute(
                """
                UPDATE sessions
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (session_id,),
            )
        return message_id

    def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        if not query.strip():
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    m.id AS message_id,
                    m.session_id,
                    s.user_id,
                    s.thread_id,
                    s.title,
                    m.role,
                    m.content,
                    m.reasoning,
                    m.tool_calls,
                    m.token_count,
                    m.created_at
                FROM messages_fts
                JOIN messages AS m ON m.id = messages_fts.message_id
                JOIN sessions AS s ON s.id = m.session_id
                WHERE messages_fts MATCH ?
                ORDER BY CASE WHEN m.role = 'user' THEN 0 ELSE 1 END, m.created_at DESC
                LIMIT ?
                """,
                (_fts_query(query), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_sessions(
        self,
        user_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        sql = [
            """
            SELECT id, user_id, thread_id, title, task_type, started_at, updated_at, status, score
            FROM sessions
            WHERE 1 = 1
            """
        ]
        params: list[object] = []
        if user_id is not None:
            sql.append("AND user_id = ?")
            params.append(user_id)
        if thread_id is not None:
            sql.append("AND thread_id = ?")
            params.append(thread_id)
        sql.append("ORDER BY updated_at DESC LIMIT ?")
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute("\n".join(sql), params).fetchall()
        return [dict(row) for row in rows]

    def get_session_messages(self, session_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    rowid AS row_number,
                    id AS message_id,
                    session_id,
                    role,
                    content,
                    reasoning,
                    tool_calls,
                    token_count,
                    created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY rowid ASC
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_thread_messages(self, user_id: str, thread_id: str, limit: int = 6) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT m.id AS message_id, m.session_id, m.role, m.content, m.created_at
                FROM messages AS m
                JOIN sessions AS s ON s.id = m.session_id
                WHERE s.user_id = ? AND s.thread_id = ?
                ORDER BY m.rowid DESC
                LIMIT ?
                """,
                (user_id, thread_id, limit),
            ).fetchall()
        return list(reversed([dict(row) for row in rows]))

    def upsert_thread_summary(
        self,
        user_id: str,
        thread_id: str,
        summary: str,
        latest_session_id: str | None = None,
        final_summary: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO thread_summaries (
                    thread_id, user_id, summary, latest_session_id, final_summary
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    summary = excluded.summary,
                    latest_session_id = excluded.latest_session_id,
                    final_summary = excluded.final_summary,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (thread_id, user_id, summary, latest_session_id, final_summary),
            )

    def get_thread_summary(self, thread_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT thread_id, user_id, summary, latest_session_id, final_summary, created_at, updated_at
                FROM thread_summaries
                WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def upsert_memory_fact(
        self,
        namespace: str,
        key: str,
        value: dict,
        source_session_id: str | None = None,
        confidence: float = 1.0,
    ) -> str:
        fact_id = str(uuid4())
        value_json = json.dumps(value, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_facts (
                    id, namespace, key, value_json, source_session_id, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    source_session_id = excluded.source_session_id,
                    confidence = excluded.confidence,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (fact_id, namespace, key, value_json, source_session_id, confidence),
            )
            row = conn.execute(
                "SELECT id FROM memory_facts WHERE namespace = ? AND key = ?",
                (namespace, key),
            ).fetchone()
        return str(row["id"])

    def list_memory_facts(self, namespace_prefix: str, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, namespace, key, value_json, source_session_id, confidence, created_at, updated_at
                FROM memory_facts
                WHERE namespace LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (f"{namespace_prefix}%", limit),
            ).fetchall()
        return [self._decode_json_field(dict(row), "value_json", "value") for row in rows]

    def delete_memory_fact(self, fact_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM memory_facts WHERE id = ?", (fact_id,))
        return cursor.rowcount > 0

    def upsert_project_memory(
        self,
        kind: str,
        key: str,
        value: dict,
        source_session_id: str | None = None,
    ) -> str:
        memory_id = str(uuid4())
        value_json = json.dumps(value, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO project_memory (id, kind, key, value_json, source_session_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(kind, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    source_session_id = excluded.source_session_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (memory_id, kind, key, value_json, source_session_id),
            )
            row = conn.execute(
                "SELECT id FROM project_memory WHERE kind = ? AND key = ?",
                (kind, key),
            ).fetchone()
        return str(row["id"])

    def search_project_memory(self, query: str, limit: int = 10) -> list[dict]:
        like = f"%{query}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, kind, key, value_json, source_session_id, created_at, updated_at
                FROM project_memory
                WHERE key LIKE ? OR value_json LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, limit),
            ).fetchall()
        return [self._decode_json_field(dict(row), "value_json", "value") for row in rows]

    def upsert_evidence_memory(
        self,
        product_name: str | None,
        title: str,
        source_url: str | None = None,
        source_tier: str = "S5",
        chunk_id: str | None = None,
        file_hash: str | None = None,
        source_session_id: str | None = None,
    ) -> str:
        memory_id = str(uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence_memory (
                    id, product_name, title, source_url, source_tier, chunk_id, file_hash, source_session_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_url, chunk_id, file_hash) DO UPDATE SET
                    product_name = excluded.product_name,
                    title = excluded.title,
                    source_tier = excluded.source_tier,
                    source_session_id = excluded.source_session_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (memory_id, product_name, title, source_url, source_tier, chunk_id, file_hash, source_session_id),
            )
            row = conn.execute(
                """
                SELECT id
                FROM evidence_memory
                WHERE source_url IS ? AND chunk_id IS ? AND file_hash IS ?
                """,
                (source_url, chunk_id, file_hash),
            ).fetchone()
        return str(row["id"])

    def search_evidence_memory(self, query: str, limit: int = 10) -> list[dict]:
        like = f"%{query}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, product_name, title, source_url, source_tier, chunk_id, file_hash,
                       source_session_id, created_at, updated_at
                FROM evidence_memory
                WHERE product_name LIKE ? OR title LIKE ? OR source_url LIKE ? OR chunk_id LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, like, like, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_tool_events(self, query: str, limit: int = 20) -> list[dict]:
        like = f"%{query}%"
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, thread_id, node, tool, input_json, output_json,
                       url, file_path, status, error, duration_ms, created_at
                FROM tool_events
                WHERE node LIKE ?
                   OR tool LIKE ?
                   OR input_json LIKE ?
                   OR output_json LIKE ?
                   OR url LIKE ?
                   OR file_path LIKE ?
                   OR error LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (like, like, like, like, like, like, like, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def export_session_jsonl(self, session_id: str) -> str:
        messages = self.get_session_messages(session_id=session_id, limit=10000)
        lines = []
        for message in messages:
            lines.append(json.dumps(message, ensure_ascii=False))
        return "\n".join(lines)

    def recall_memory(self, user_id: str, thread_id: str, query: str, limit: int = 10) -> dict:
        thread_summary = self.get_thread_summary(thread_id)
        facts = self.list_memory_facts(f"user:{user_id}:", limit=limit)
        project_memories = self.search_project_memory(query, limit=limit) if query.strip() else []
        evidence_memories = self.search_evidence_memory(query, limit=limit) if query.strip() else []
        messages = self.search_messages(query, limit=limit) if query.strip() else []

        citations: list[dict] = []
        if thread_summary is not None:
            citations.append(
                {
                    "source": "thread_summary",
                    "id": thread_summary["thread_id"],
                    "label": thread_summary["summary"],
                }
            )
        for item in facts:
            citations.append({"source": "memory_fact", "id": item["id"], "label": item["key"]})
        for item in project_memories:
            citations.append({"source": "project_memory", "id": item["id"], "label": item["key"]})
        for item in evidence_memories:
            citations.append({"source": "evidence_memory", "id": item["id"], "label": item["title"]})
        for item in messages:
            citations.append({"source": "message", "id": item["message_id"], "label": item["content"][:80]})

        return {
            "thread_summary": thread_summary,
            "facts": facts,
            "project_memories": project_memories,
            "evidence_memories": evidence_memories,
            "messages": messages,
            "citations": citations,
        }

    def _decode_json_field(self, row: dict, source_key: str, target_key: str) -> dict:
        raw_value = row.pop(source_key)
        try:
            row[target_key] = json.loads(raw_value)
        except json.JSONDecodeError:
            row[target_key] = {}
        return row


def _fts_query(query: str) -> str:
    return f'"{query.replace("\"", "\"\"")}"'
