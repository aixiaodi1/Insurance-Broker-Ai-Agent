import json
from pathlib import Path

from app.services.evidence_source_registry import EvidenceSourceRegistry


def test_registry_finds_company_entry_and_product_materials(tmp_path: Path) -> None:
    data_dir = tmp_path
    specs_dir = data_dir / "insurance_harness" / "specs"
    cleaned_dir = data_dir / "insurance_harness" / "cleaned"
    specs_dir.mkdir(parents=True)
    cleaned_dir.mkdir(parents=True)

    (specs_dir / "太平人寿.json").write_text(
        json.dumps(
            {
                "company": "太平人寿保险有限公司",
                "crawl_method": "playwright",
                "source_url": "https://life.cntaiping.com/info-zstscp/",
                "pdf_host": "life.cntaiping.com",
                "total_products": 1,
                "total_pdf_links": 1,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cleaned_dir / "pdf_download_links.jsonl").write_text(
        json.dumps(
            {
                "company": "太平人寿",
                "product_name": "太平乐享居一号养老年金保险（分红型）",
                "status": "在售",
                "file_type": "产品条款",
                "url": "https://life.cntaiping.com/upload/cms/life/demo.pdf",
                "extension": "pdf",
                "source_file": "太平人寿.json",
                "source_kind": "explicit",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    registry = EvidenceSourceRegistry(data_dir)
    result = registry.query("帮我找太平乐享居一号的官方资料")

    assert result["enabled"] is True
    assert result["companyMatches"][0]["company"] == "太平人寿保险有限公司"
    assert result["companyMatches"][0]["sourceTier"] == "S2_OFFICIAL_SPEC"
    assert result["materialMatches"][0]["productName"] == "太平乐享居一号养老年金保险（分红型）"
    assert result["materialMatches"][0]["sourceTier"] == "S1_OFFICIAL_PDF"
    assert result["materialMatches"][0]["url"] == "https://life.cntaiping.com/upload/cms/life/demo.pdf"


def test_registry_ranks_company_and_product_overlap_above_partial_product_overlap(tmp_path: Path) -> None:
    data_dir = tmp_path
    cleaned_dir = data_dir / "insurance_harness" / "cleaned"
    cleaned_dir.mkdir(parents=True)

    rows = [
        {
            "company": "上海人寿",
            "product_name": "上海人寿增利宝乐享版终身寿险（万能型）",
            "status": "在售",
            "file_type": "产品条款",
            "url": "https://example.com/shanghai.pdf",
            "extension": "pdf",
            "source_file": "上海人寿.json",
            "source_kind": "explicit",
        },
        {
            "company": "太平人寿",
            "product_name": "太平乐享居一号养老年金保险（分红型）",
            "status": "在售",
            "file_type": "产品条款",
            "url": "https://example.com/taiping.pdf",
            "extension": "pdf",
            "source_file": "太平人寿.json",
            "source_kind": "explicit",
        },
    ]
    (cleaned_dir / "pdf_download_links.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    registry = EvidenceSourceRegistry(data_dir)
    result = registry.query("帮我找太平乐享居一号官方资料")

    assert result["materialMatches"][0]["company"] == "太平人寿"
    assert result["materialMatches"][0]["url"] == "https://example.com/taiping.pdf"
