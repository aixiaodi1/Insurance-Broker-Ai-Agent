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


def test_admin_page_hosts_agent_debug_workbench() -> None:
    client = TestClient(create_app())
    response = client.get("/admin")

    assert response.status_code == 200
    assert "RAG 调试台" in response.text
    assert "运行轨迹" in response.text
    assert "事件列表" in response.text
    assert "工具调用" in response.text
    assert "向量命中" in response.text
    assert "请求内容" in response.text
    assert "响应内容" in response.text
    assert 'data-debug-endpoint="/agent/run_v2"' in response.text


def test_admin_script_renders_migrated_debug_payload_sections() -> None:
    client = TestClient(create_app())
    response = client.get("/static/admin.js")

    assert response.status_code == 200
    assert "renderDebugRunDetails" in response.text
    assert "renderDebugNodes" in response.text
    assert "renderDebugEvents" in response.text
    assert "renderDebugToolCalls" in response.text
    assert "renderDebugVectorMatches" in response.text
    assert "requestJson" in response.text
    assert "responseJson" in response.text
