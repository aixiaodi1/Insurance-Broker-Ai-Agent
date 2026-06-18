from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class RunControlStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    interrupt_requested INTEGER NOT NULL DEFAULT 0,
                    state_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_guidance (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    content TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES agent_runs(id)
                );

                CREATE TABLE IF NOT EXISTS agent_run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES agent_runs(id)
                );
                """
            )

    def start_run(self, run_id: str, thread_id: str, user_id: str, state: dict) -> None:
        now = _now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs (id, thread_id, user_id, status, interrupt_requested, state_json, created_at, updated_at)
                VALUES (?, ?, ?, 'running', 0, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    thread_id = excluded.thread_id,
                    user_id = excluded.user_id,
                    status = 'running',
                    interrupt_requested = 0,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (run_id, thread_id, user_id, json.dumps(state, ensure_ascii=False), now, now),
            )

    def get_run(self, run_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["interrupt_requested"] = bool(payload["interrupt_requested"])
        payload["state"] = json.loads(payload.pop("state_json") or "{}")
        return payload

    def get_latest_thread_run(self, thread_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM agent_runs WHERE thread_id = ? ORDER BY rowid DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        return self.get_run(str(row["id"])) if row is not None else None

    def request_interrupt(self, run_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE agent_runs SET interrupt_requested = 1, updated_at = ? WHERE id = ?",
                (_now(), run_id),
            )
        return cursor.rowcount > 0

    def interrupt_requested(self, run_id: str) -> bool:
        run = self.get_run(run_id)
        return bool(run and run["interrupt_requested"])

    def upsert_guidance(self, run_id: str, content: str, priority: str) -> dict | None:
        if self.get_run(run_id) is None:
            return None
        now = _now()
        guidance_id = f"guidance_{uuid4().hex}"
        with self.connect() as connection:
            existing = connection.execute("SELECT id FROM agent_guidance WHERE run_id = ?", (run_id,)).fetchone()
            if existing is not None:
                guidance_id = str(existing["id"])
            connection.execute(
                """
                INSERT INTO agent_guidance (id, run_id, content, priority, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    content = excluded.content,
                    priority = excluded.priority,
                    status = 'pending',
                    updated_at = excluded.updated_at
                """,
                (guidance_id, run_id, content, priority, now, now),
            )
        return self.get_pending_guidance(run_id)

    def get_pending_guidance(self, run_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, run_id, content, priority, status, created_at, updated_at FROM agent_guidance WHERE run_id = ? AND status = 'pending'",
                (run_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def mark_guidance_applied(self, run_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE agent_guidance SET status = 'applied', updated_at = ? WHERE run_id = ? AND status = 'pending'",
                (_now(), run_id),
            )

    def delete_guidance(self, run_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute("DELETE FROM agent_guidance WHERE run_id = ? AND status = 'pending'", (run_id,))
        return cursor.rowcount > 0

    def append_event(self, run_id: str, event: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO agent_run_events (run_id, event_json, created_at) VALUES (?, ?, ?)",
                (run_id, json.dumps(event, ensure_ascii=False, default=str), _now()),
            )

    def finish_run(self, run_id: str, status: str, state: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET status = ?, state_json = ?, updated_at = ? WHERE id = ?",
                (status, json.dumps(state, ensure_ascii=False, default=str), _now(), run_id),
            )


def _now() -> str:
    return datetime.now(UTC).isoformat()
