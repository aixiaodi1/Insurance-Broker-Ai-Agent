from pathlib import Path


def test_gitignore_excludes_generated_runtime_artifacts():
    text = Path(".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in text
    assert ".pytest_cache/" in text
    assert "data/**/*.sqlite3" in text
    assert "data/runs/**/events.jsonl" in text
