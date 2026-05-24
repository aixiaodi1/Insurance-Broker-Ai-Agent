from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["admin"])
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "admin.html"


@router.get("/admin", response_class=HTMLResponse)
def admin_page() -> HTMLResponse:
    return HTMLResponse(TEMPLATE_PATH.read_text(encoding="utf-8"))
