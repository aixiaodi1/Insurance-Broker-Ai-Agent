from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from app.web_acquisition.schemas import AcquisitionResult


class SQLiteAcquisitionStore:
    def __init__(self, db_path: Path) -> None:
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
                CREATE TABLE IF NOT EXISTS acquisition_tasks (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    allowed_domains_json TEXT DEFAULT '[]',
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS acquisition_steps (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    layer TEXT NOT NULL,
                    action TEXT NOT NULL,
                    description TEXT NOT NULL,
                    url_before TEXT,
                    url_after TEXT,
                    screenshot_path TEXT,
                    metadata_json TEXT DEFAULT '{}',
                    FOREIGN KEY(task_id) REFERENCES acquisition_tasks(id)
                );

                CREATE TABLE IF NOT EXISTS discovered_links (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    text TEXT DEFAULT '',
                    document_type TEXT DEFAULT 'unknown',
                    confidence REAL DEFAULT 0,
                    source TEXT DEFAULT 'unknown',
                    source_page TEXT DEFAULT '',
                    is_pdf INTEGER DEFAULT 0,
                    FOREIGN KEY(task_id) REFERENCES acquisition_tasks(id)
                );

                CREATE TABLE IF NOT EXISTS downloaded_files (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    final_url TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES acquisition_tasks(id)
                );

                CREATE TABLE IF NOT EXISTS site_harnesses (
                    domain TEXT PRIMARY KEY,
                    harness_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def create_task(self, url: str, goal: str, allowed_domains: list[str] | None, strategy: str) -> str:
        task_id = str(uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO acquisition_tasks (id, url, goal, allowed_domains_json, strategy, status)
                VALUES (?, ?, ?, ?, ?, 'running')
                """,
                (task_id, url, goal, json.dumps(allowed_domains or [], ensure_ascii=False), strategy),
            )
        return task_id

    def finish_task(self, task_id: str, status: str, result: AcquisitionResult) -> None:
        result_dict = asdict(result)
        with self.connect() as conn:
            conn.execute("DELETE FROM acquisition_steps WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM discovered_links WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM downloaded_files WHERE task_id = ?", (task_id,))
            conn.execute(
                """
                UPDATE acquisition_tasks
                SET status = ?, result_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, json.dumps(result_dict, ensure_ascii=False), task_id),
            )
            for index, step in enumerate(result.steps):
                conn.execute(
                    """
                    INSERT INTO acquisition_steps (
                        id, task_id, step_index, layer, action, description,
                        url_before, url_after, screenshot_path, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        task_id,
                        index,
                        step.layer,
                        step.action,
                        step.description,
                        step.url_before,
                        step.url_after,
                        step.screenshot_path,
                        json.dumps(step.metadata, ensure_ascii=False),
                    ),
                )
            pdf_urls = {link.url for link in result.pdf_links}
            seen_link_urls = {link.url for link in result.links}
            links = result.links + [link for link in result.pdf_links if link.url not in seen_link_urls]
            for link in links:
                conn.execute(
                    """
                    INSERT INTO discovered_links (
                        id, task_id, url, text, document_type, confidence, source, source_page, is_pdf
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        task_id,
                        link.url,
                        link.text,
                        link.document_type,
                        link.confidence,
                        link.source,
                        link.source_page,
                        1 if link.url in pdf_urls else 0,
                    ),
                )
            for file in result.downloaded_files:
                conn.execute(
                    """
                    INSERT INTO downloaded_files (
                        id, task_id, source_url, final_url, file_path, filename,
                        content_type, size_bytes, sha256
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        task_id,
                        file.source_url,
                        file.final_url,
                        file.file_path,
                        file.filename,
                        file.content_type,
                        file.size_bytes,
                        file.sha256,
                    ),
                )

    def get_task(self, task_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id, url, goal, allowed_domains_json, strategy, status, result_json, created_at, updated_at
                FROM acquisition_tasks
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        task = dict(row)
        task["allowed_domains"] = json.loads(task.pop("allowed_domains_json") or "[]")
        raw_result = task.pop("result_json")
        task["result"] = json.loads(raw_result) if raw_result else None
        return task

    def list_steps(self, task_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT step_index, layer, action, description, url_before, url_after, screenshot_path, metadata_json
                FROM acquisition_steps
                WHERE task_id = ?
                ORDER BY step_index ASC
                """,
                (task_id,),
            ).fetchall()
        return [self._decode_json_field(dict(row), "metadata_json", "metadata") for row in rows]

    def list_links(self, task_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT url, text, document_type, confidence, source, source_page, is_pdf
                FROM discovered_links
                WHERE task_id = ?
                ORDER BY rowid ASC
                """,
                (task_id,),
            ).fetchall()
        return [self._decode_bool(dict(row), "is_pdf") for row in rows]

    def list_files(self, task_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT source_url, final_url, file_path, filename, content_type, size_bytes, sha256
                FROM downloaded_files
                WHERE task_id = ?
                ORDER BY rowid ASC
                """,
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_site_harness(self, domain: str, harness_name: str, enabled: bool = True) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO site_harnesses (domain, harness_name, enabled)
                VALUES (?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    harness_name = excluded.harness_name,
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (domain.lower().strip("."), harness_name, 1 if enabled else 0),
            )

    def list_site_harnesses(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT domain, harness_name, enabled
                FROM site_harnesses
                ORDER BY domain ASC
                """
            ).fetchall()
        return [self._decode_bool(dict(row), "enabled") for row in rows]

    def _decode_json_field(self, row: dict, source_key: str, target_key: str) -> dict:
        raw_value = row.pop(source_key)
        try:
            row[target_key] = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            row[target_key] = {}
        return row

    def _decode_bool(self, row: dict, key: str) -> dict:
        row[key] = bool(row[key])
        return row
