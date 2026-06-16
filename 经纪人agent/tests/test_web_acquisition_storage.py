from __future__ import annotations

from app.web_acquisition.schemas import AcquisitionResult, AcquisitionStep, DiscoveredLink, DownloadedFile
from app.web_acquisition.storage import SQLiteAcquisitionStore


def test_store_persists_task_result_steps_links_and_files(tmp_path):
    store = SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3")
    store.init_schema()
    task_id = store.create_task(
        url="https://www.example.com/product",
        goal="find product files",
        allowed_domains=["example.com"],
        strategy="auto",
    )
    result = AcquisitionResult(
        success=True,
        input_url="https://www.example.com/product",
        final_url="https://www.example.com/product",
        strategy_used="http",
        title="Example Product",
        text="保险 产品 条款",
        links=[DiscoveredLink(url="https://www.example.com/product", text="Product", source="http")],
        pdf_links=[DiscoveredLink(url="https://www.example.com/clause.pdf", text="产品条款", source="http")],
        downloaded_files=[
            DownloadedFile(
                source_url="https://www.example.com/clause.pdf",
                final_url="https://www.example.com/clause.pdf",
                file_path="data/downloads/clause.pdf",
                filename="clause.pdf",
                content_type="application/pdf",
                size_bytes=12,
                sha256="abc123",
            )
        ],
        steps=[AcquisitionStep(layer="http", action="fetch", description="Fetched page")],
        quality_score=0.9,
    )

    store.finish_task(task_id, "succeeded", result)

    task = store.get_task(task_id)
    assert task is not None
    assert task["status"] == "succeeded"
    assert task["url"] == "https://www.example.com/product"
    assert task["allowed_domains"] == ["example.com"]
    assert task["result"]["strategy_used"] == "http"
    assert task["result"]["title"] == "Example Product"
    assert store.list_steps(task_id)[0]["description"] == "Fetched page"
    assert store.list_files(task_id)[0]["sha256"] == "abc123"
    assert store.list_links(task_id)[0]["url"] == "https://www.example.com/product"


def test_store_records_failed_task_with_structured_errors(tmp_path):
    store = SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3")
    store.init_schema()
    task_id = store.create_task("http://localhost/internal", "goal", None, "auto")
    result = AcquisitionResult(
        success=False,
        input_url="http://localhost/internal",
        strategy_used="none",
        errors=[],
    )

    store.finish_task(task_id, "failed", result)

    task = store.get_task(task_id)
    assert task is not None
    assert task["status"] == "failed"
    assert task["result"]["success"] is False


def test_store_persists_pdf_links_even_when_not_in_general_links(tmp_path):
    store = SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3")
    store.init_schema()
    task_id = store.create_task("https://www.example.com/product", "goal", None, "auto")
    result = AcquisitionResult(
        success=True,
        input_url="https://www.example.com/product",
        strategy_used="browser_use",
        pdf_links=[DiscoveredLink(url="https://www.example.com/clause.pdf", text="产品条款", source="browser_use")],
    )

    store.finish_task(task_id, "succeeded", result)

    links = store.list_links(task_id)
    assert links == [
        {
            "url": "https://www.example.com/clause.pdf",
            "text": "产品条款",
            "document_type": "unknown",
            "confidence": 0.0,
            "source": "browser_use",
            "source_page": "",
            "is_pdf": True,
        }
    ]


def test_store_upserts_site_harness_metadata(tmp_path):
    store = SQLiteAcquisitionStore(tmp_path / "acquisition.sqlite3")
    store.init_schema()

    store.upsert_site_harness("example.com", "ExampleHarness", enabled=True)
    store.upsert_site_harness("example.com", "RenamedHarness", enabled=False)

    harnesses = store.list_site_harnesses()
    assert harnesses == [{"domain": "example.com", "harness_name": "RenamedHarness", "enabled": False}]
