from fastapi.testclient import TestClient

from app.main import create_app


def test_admin_page_contains_three_required_areas() -> None:
    client = TestClient(create_app())
    response = client.get("/admin")

    assert response.status_code == 200
    assert "上传区" in response.text
    assert "任务区" in response.text
    assert "文档区" in response.text
    assert "/documents/upload" in response.text
    assert "/jobs/" in response.text
    assert "/documents" in response.text
