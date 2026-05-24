from fastapi import APIRouter, Depends

from app.dependencies import get_vector_store
from app.infrastructure.vectorstores.base import VectorStore


router = APIRouter(tags=["collections"])


@router.get("/collections")
def list_collections(vector_store: VectorStore = Depends(get_vector_store)) -> dict:
    return {"collections": vector_store.list_collections()}
