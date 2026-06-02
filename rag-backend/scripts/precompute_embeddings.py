"""Phase 1: Load chunks and compute embeddings via local API, save to JSON."""

import json
import sys
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import get_settings
from app.infrastructure.repositories.sqlite import SQLiteRepository


TEST_QUERIES = [
    "等待期是多少天",
    "重疾保险金怎么赔",
    "酒驾赔不赔",
    "原位癌算不算轻症",
    "理赔需要什么材料",
]


def load_chunks(settings):
    repo = SQLiteRepository(settings.database_url)
    repo.initialize()
    conn = repo._connect()
    try:
        rows = conn.execute(
            "SELECT chroma_id, COALESCE(content_text, content_preview) AS content_text, source_file, chunk_index, "
            "section_no, section_title, content_type, parent_id, document_id "
            "FROM chunks WHERE type = 'child' OR type IS NULL LIMIT 500"
        ).fetchall()
    except Exception:
        rows = conn.execute(
            "SELECT chroma_id, COALESCE(content_text, content_preview) AS content_text, source_file, chunk_index, "
            "section_no, section_title, content_type, parent_id, document_id "
            "FROM chunks LIMIT 500"
        ).fetchall()
    conn.close()
    chunks = []
    for row in rows:
        meta = {
            "source_file": row["source_file"],
            "chunk_index": row["chunk_index"],
            "section_no": row["section_no"] or "",
            "section_title": row["section_title"] or "",
            "content_type": row["content_type"] or "",
            "parent_id": row["parent_id"] or "",
            "document_id": row["document_id"],
        }
        chunks.append({
            "id": row["chroma_id"],
            "text": row["content_text"],
            "metadata": meta,
        })
    return chunks


def embed_via_api(texts, settings):
    url = f"{settings.embedding_api_base_url.rstrip('/')}{settings.embedding_api_path}"
    headers = {"Content-Type": "application/json"}
    if settings.embedding_api_key:
        headers["Authorization"] = f"Bearer {settings.embedding_api_key}"
    payload = json.dumps({"input": texts, "model": settings.embedding_model}).encode()
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return [item["embedding"] for item in data["data"]]


def main():
    settings = get_settings()
    chunks = load_chunks(settings)
    print(f"Loaded {len(chunks)} chunks")
    texts = [c["text"] for c in chunks]

    all_embeddings = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        all_embeddings.extend(embed_via_api(batch, settings))
        print(f"  embedded {min(i+batch_size, len(texts))}/{len(texts)}")
    print(f"  Dimension: {len(all_embeddings[0])}")

    q_embeddings = embed_via_api(TEST_QUERIES, settings)
    print(f"  Embedded {len(TEST_QUERIES)} test queries")

    out = {
        "ids": [c["id"] for c in chunks],
        "texts": texts,
        "metadatas": [c["metadata"] for c in chunks],
        "embeddings": all_embeddings,
        "test_queries": TEST_QUERIES,
        "test_query_embeddings": q_embeddings,
    }
    out_path = _PROJECT_ROOT / "data" / "shadow_embeddings.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()
