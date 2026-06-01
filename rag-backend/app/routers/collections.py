from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_vector_store
from app.infrastructure.vectorstores.base import VectorStore


router = APIRouter(tags=["collections"])


@router.get("/collections")
def list_collections(vector_store: VectorStore = Depends(get_vector_store)) -> dict:
    return {"collections": vector_store.list_collections()}


@router.delete("/collections/{name}")
def delete_collection(name: str, vector_store: VectorStore = Depends(get_vector_store)) -> dict:
    collections = vector_store.list_collections()
    if name not in collections:
        raise HTTPException(status_code=404, detail=f"Collection '{name}' not found")
    vector_store.delete_collection(name)
    return {"status": "ok", "deleted": name}
