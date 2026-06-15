from __future__ import annotations

import json
from pathlib import Path
from time import time
from uuid import uuid4

from app.memory.sqlite_memory import SQLiteMemory


class AuditLogger:
    def __init__(self, memory: SQLiteMemory, runs_dir: Path):
        self.memory = memory
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def log_tool_event(
        self,
        run_id: str,
        thread_id: str,
        node: str,
        tool: str,
        status: str,
        input_json: dict,
        output_json: dict,
        url: str | None = None,
        file_path: str | None = None,
        error: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        event = {
            "id": str(uuid4()),
            "run_id": run_id,
            "thread_id": thread_id,
            "timestamp": time(),
            "node": node,
            "tool": tool,
            "input_json": input_json,
            "output_json": output_json,
            "url": url,
            "file_path": file_path,
            "status": status,
            "error": error,
            "duration_ms": duration_ms,
        }
        with self.memory.connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_events (
                    id, run_id, thread_id, node, tool, input_json, output_json,
                    url, file_path, status, error, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["id"],
                    run_id,
                    thread_id,
                    node,
                    tool,
                    json.dumps(input_json, ensure_ascii=False),
                    json.dumps(output_json, ensure_ascii=False),
                    url,
                    file_path,
                    status,
                    error,
                    duration_ms,
                ),
            )

        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
