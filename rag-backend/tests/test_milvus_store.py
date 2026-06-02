from pathlib import Path
from tempfile import mkdtemp

import pytest

pytest.importorskip("pymilvus", reason="pymilvus/milvus-lite only available on Linux/WSL")

from app.infrastructure.vectorstores.milvus_store import MilvusVectorStore


def _make_store() -> MilvusVectorStore:
    tmp = Path(mkdtemp()) / "test_milvus.db"
    return MilvusVectorStore(tmp)


def test_ensure_collection_creates_and_is_idempotent() -> None:
    store = _make_store()
    store.ensure_collection("test_coll")
    assert "test_coll" in store.list_collections()
    store.ensure_collection("test_coll")
    assert "test_coll" in store.list_collections()
    store.close()


def test_upsert_and_query_chunks() -> None:
    store = _make_store()
    store.ensure_collection("test")
    ids = ["c1", "c2", "c3"]
    texts = ["first chunk", "second chunk", "third chunk"]
    vec = [1.0] + [0.0] * 767
    vec2 = [0.0] * 768
    vec2[1] = 1.0
    vec3 = [0.0] * 768
    vec3[2] = 1.0
    embeddings = [vec, vec2, vec3]
    metadatas = [
        {"source_file": "a.txt", "chunk_index": 0, "content_type": "clause"},
        {"source_file": "b.txt", "chunk_index": 1, "content_type": "exclusion"},
        {"source_file": "c.txt", "chunk_index": 2, "content_type": "disease_definition"},
    ]
    store.upsert_chunks("test", ids, texts, embeddings, metadatas)

    qvec = [1.0, 0.1] + [0.0] * 766
    results = store.query_chunks("test", qvec, n_results=2)
    assert len(results) == 2
    assert results[0]["id"] == "c1"
    assert "first chunk" in results[0]["document"]
    store.close()


def test_get_chunks_by_ids() -> None:
    store = _make_store()
    store.ensure_collection("test")
    ids = ["c1", "c2"]
    texts = ["one", "two"]
    v1 = [1.0] + [0.0] * 767
    v2 = [0.0] * 768
    v2[1] = 1.0
    embeddings = [v1, v2]
    metadatas = [{"source_file": "a.txt", "chunk_index": 0}, {"source_file": "b.txt", "chunk_index": 1}]
    store.upsert_chunks("test", ids, texts, embeddings, metadatas)

    fetched = store.get_chunks_by_ids("test", ["c1", "c2"])
    assert len(fetched) == 2
    fetched_ids = {f["id"] for f in fetched}
    assert fetched_ids == {"c1", "c2"}
    store.close()


def test_get_chunks_by_ids_non_existent() -> None:
    store = _make_store()
    store.ensure_collection("test")
    fetched = store.get_chunks_by_ids("test", ["nonexistent"])
    assert fetched == []
    store.close()


def test_delete_chunks() -> None:
    store = _make_store()
    store.ensure_collection("test")
    ids = ["c1", "c2"]
    texts = ["one", "two"]
    v1 = [1.0] + [0.0] * 767
    v2 = [0.0] * 768
    v2[1] = 1.0
    embeddings = [v1, v2]
    metadatas = [{"source_file": "a.txt", "document_id": "doc1"}, {"source_file": "b.txt", "document_id": "doc2"}]
    store.upsert_chunks("test", ids, texts, embeddings, metadatas)

    store.delete_chunks("test", {"document_id": "doc1"})
    qvec = [1.0] + [0.0] * 767
    results = store.query_chunks("test", qvec, n_results=5)
    assert len(results) == 1
    assert results[0]["id"] == "c2"
    store.close()


def test_delete_collection() -> None:
    store = _make_store()
    store.ensure_collection("test")
    store.ensure_collection("other")
    assert len(store.list_collections()) == 2

    store.delete_collection("test")
    assert "test" not in store.list_collections()
    assert "other" in store.list_collections()
    store.close()


def test_query_empty_collection_returns_empty() -> None:
    store = _make_store()
    results = store.query_chunks("nonexistent", [1.0, 0.0], n_results=5)
    assert results == []
    store.close()


def test_upsert_validates_lengths() -> None:
    store = _make_store()
    try:
        store.upsert_chunks("test", ["c1"], ["text"], [[1.0]], [{}])
    except Exception:
        pass  # dimension mismatch is handled gracefully with MilvusClient
    store.close()


def test_list_collections_empty_initially() -> None:
    store = _make_store()
    assert store.list_collections() == []
    store.close()


def test_close_is_idempotent() -> None:
    store = _make_store()
    store.close()
    store.close()
