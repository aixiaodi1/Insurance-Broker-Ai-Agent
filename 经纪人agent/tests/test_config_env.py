from __future__ import annotations

import os

from app.config import load_project_env


def test_project_env_loader_reads_file_without_overriding_process_env(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "BAIDU_QIANFAN_API_KEY=from-file\nFIRECRAWL_API_KEY=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("BAIDU_QIANFAN_API_KEY", raising=False)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "from-process")

    load_project_env(tmp_path)

    assert os.environ["BAIDU_QIANFAN_API_KEY"] == "from-file"
    assert os.environ["FIRECRAWL_API_KEY"] == "from-process"
