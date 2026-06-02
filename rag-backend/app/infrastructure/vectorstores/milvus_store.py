from pathlib import Path

from app.errors import NonRetryableIngestionError, RetryableIngestionError


class MilvusVectorStore:
    def __init__(self, db_path: Path, dimension: int = 768) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        from pymilvus import MilvusClient
        self._client = MilvusClient(str(db_path))
        self._db_path = db_path
        self._closed = False
        self._dimension = dimension

    def close(self) -> None:
        if self._closed:
            return
        self._client.close()
        self._closed = True

    def ensure_collection(self, name: str) -> None:
        from pymilvus import CollectionSchema, DataType, FieldSchema
        from pymilvus.milvus_client.index import IndexParams, IndexParam

        if self._client.has_collection(name):
            self._client.load_collection(name)
            return
        schema = CollectionSchema([
            FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=512),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=self._dimension),
            FieldSchema(name="document", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="source_file", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(name="section_no", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="section_title", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="content_type", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=512),
        ])
        index_params = IndexParams([IndexParam(
            field_name="vector", index_type="IVF_FLAT", index_name="vector_index",
            metric_type="L2", nlist=128,
        )])
        self._client.create_collection(collection_name=name, schema=schema, index_params=index_params)
        self._client.load_collection(name)

    def list_collections(self) -> list[str]:
        return self._client.list_collections()

    def upsert_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        if len({len(ids), len(texts), len(embeddings), len(metadatas)}) != 1:
            raise NonRetryableIngestionError("Milvus chunk ids, texts, embeddings, and metadatas must have the same length.")
        if not ids:
            raise NonRetryableIngestionError("Milvus chunk upsert requires at least one chunk.")
        if len(ids) != len(set(ids)):
            raise NonRetryableIngestionError("Milvus chunk ids must not contain duplicate values.")

        self.ensure_collection(collection)
        rows = []
        for i, cid in enumerate(ids):
            meta = metadatas[i] if isinstance(metadatas[i], dict) else {}
            rows.append({
                "id": cid,
                "vector": embeddings[i],
                "document": texts[i],
                "source_file": str(meta.get("source_file", "")),
                "chunk_index": int(meta.get("chunk_index", -1)),
                "section_no": str(meta.get("section_no", "")),
                "section_title": str(meta.get("section_title", "")),
                "content_type": str(meta.get("content_type", "")),
                "parent_id": str(meta.get("parent_id", "")),
                "document_id": str(meta.get("document_id", "")),
            })
        try:
            self._client.upsert(collection_name=collection, data=rows)
        except Exception as exc:
            raise RetryableIngestionError(f"Milvus write failed: {exc}") from exc

    def query_chunks(self, collection: str, embedding: list[float], n_results: int = 5, where: dict | None = None) -> list[dict]:
        if not self._client.has_collection(collection):
            return []
        try:
            search_kwargs = dict(
                collection_name=collection,
                data=[embedding],
                anns_field="vector",
                limit=n_results,
                output_fields=["id", "document", "source_file", "chunk_index",
                               "section_no", "section_title", "content_type",
                               "parent_id", "document_id"],
            )
            if where:
                search_kwargs["filter"] = " and ".join(f'{k} == "{v}"' for k, v in where.items())
            result = self._client.search(**search_kwargs)
        except Exception as exc:
            raise RetryableIngestionError(f"Milvus query failed: {exc}") from exc

        hits = result[0] if result else []
        return [
            {
                "id": hit["id"],
                "document": hit["entity"].get("document", ""),
                "metadata": {
                    "source_file": hit["entity"].get("source_file", ""),
                    "chunk_index": hit["entity"].get("chunk_index", -1),
                    "section_no": hit["entity"].get("section_no", ""),
                    "section_title": hit["entity"].get("section_title", ""),
                    "content_type": hit["entity"].get("content_type", ""),
                    "parent_id": hit["entity"].get("parent_id", ""),
                    "document_id": hit["entity"].get("document_id", ""),
                },
                "distance": hit.get("distance", 0.0),
            }
            for hit in hits
        ]

    def get_chunks_by_ids(self, collection: str, ids: list[str]) -> list[dict]:
        if not ids or not self._client.has_collection(collection):
            return []
        try:
            result = self._client.query(
                collection_name=collection,
                filter=f"id in {ids}",
                output_fields=["id", "document", "source_file", "chunk_index",
                               "section_no", "section_title", "content_type",
                               "parent_id", "document_id"],
            )
        except Exception as exc:
            raise RetryableIngestionError(f"Milvus get failed: {exc}") from exc

        return [
            {
                "id": row["id"],
                "document": row.get("document", ""),
                "metadata": {
                    "source_file": row.get("source_file", ""),
                    "chunk_index": row.get("chunk_index", -1),
                    "section_no": row.get("section_no", ""),
                    "section_title": row.get("section_title", ""),
                    "content_type": row.get("content_type", ""),
                    "parent_id": row.get("parent_id", ""),
                    "document_id": row.get("document_id", ""),
                },
            }
            for row in result
        ]

    def delete_chunks(self, collection: str, where: dict) -> None:
        if not self._client.has_collection(collection):
            return
        filter_expr = " and ".join(f'{k} == "{v}"' for k, v in where.items())
        try:
            self._client.delete(collection_name=collection, filter=filter_expr)
        except Exception as exc:
            raise RetryableIngestionError(f"Milvus delete failed: {exc}") from exc

    def delete_collection(self, name: str) -> None:
        if self._client.has_collection(name):
            self._client.drop_collection(name)

    def add_chunks(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        self.upsert_chunks(collection, ids, texts, embeddings, metadatas)
