from __future__ import annotations

import json

from app.search.providers import BaiduBrowserSearchProvider, BaiduQianfanSearchProvider, FirecrawlSearchProvider


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_baidu_qianfan_provider_sends_messages_payload_and_parses_references(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "code": 0,
                "message": "success",
                "references": [
                    {
                        "title": "官方条款",
                        "url": "https://example.com/clause.pdf",
                        "content": "产品条款 PDF",
                    }
                ],
            }
        )

    monkeypatch.setattr("app.search.providers.urlopen", fake_urlopen)

    provider = BaiduQianfanSearchProvider(api_key="test-key", endpoint="https://qianfan.example/v2/ai_search/web_search")
    result = provider.search("平安人寿御享金越保险条款 PDF 在哪里？", limit=5)

    assert captured["url"] == "https://qianfan.example/v2/ai_search/web_search"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"] == {
        "messages": [
            {
                "role": "user",
                "content": "平安人寿御享金越保险条款 PDF 在哪里？",
            }
        ]
    }
    assert result.ok is True
    assert result.results[0].title == "官方条款"
    assert result.results[0].url == "https://example.com/clause.pdf"
    assert result.results[0].snippet == "产品条款 PDF"


def test_baidu_qianfan_rejects_response_without_references(monkeypatch):
    monkeypatch.setattr("app.search.providers.urlopen", lambda request, timeout: FakeResponse({"code": 0, "results": []}))

    result = BaiduQianfanSearchProvider(api_key="test-key", endpoint="https://qianfan.example/search").search("query")

    assert result.ok is False
    assert result.error == "provider_contract_error"


def test_firecrawl_provider_sends_v2_search_payload_and_parses_web_results(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "success": True,
                "data": {
                    "web": [
                        {
                            "title": "Official disclosure",
                            "url": "https://example.com/disclosure.pdf",
                            "description": "Official PDF",
                        }
                    ]
                },
            }
        )

    monkeypatch.setattr("app.search.providers.urlopen", fake_urlopen)
    provider = FirecrawlSearchProvider(api_key="fc-test", endpoint="https://api.firecrawl.dev/v2/search")

    result = provider.search("product disclosure", limit=6)

    assert captured["url"] == "https://api.firecrawl.dev/v2/search"
    assert captured["headers"]["Authorization"] == "Bearer fc-test"
    assert captured["body"] == {"query": "product disclosure", "limit": 6, "sources": ["web"]}
    assert result.ok is True
    assert result.results[0].url == "https://example.com/disclosure.pdf"


def test_baidu_browser_provider_filters_ads_and_internal_aggregators():
    provider = BaiduBrowserSearchProvider(
        runner=lambda query, limit: [
            {"title": "广告 推广", "url": "https://ad.example/sale", "snippet": "广告"},
            {"title": "百家号解读", "url": "https://baijiahao.baidu.com/s?id=1", "snippet": "聚合"},
            {"title": "Official PDF", "url": "https://example.com/clause.pdf", "snippet": "条款"},
        ]
    )

    result = provider.search("产品条款", limit=5)

    assert result.ok is True
    assert [item.url for item in result.results] == ["https://example.com/clause.pdf"]


def test_provider_malformed_payloads_become_contract_errors(monkeypatch):
    monkeypatch.setattr("app.search.providers.urlopen", lambda request, timeout: FakeResponse(["invalid"]))

    firecrawl = FirecrawlSearchProvider(api_key="fc-test").search("query")
    browser = BaiduBrowserSearchProvider(runner=lambda query, limit: None).search("query")

    assert firecrawl.ok is False
    assert firecrawl.error == "provider_contract_error"
    assert browser.ok is False
    assert browser.error == "provider_contract_error"


def test_baidu_browser_empty_result_is_not_reported_as_success():
    result = BaiduBrowserSearchProvider(runner=lambda query, limit: []).search("query")

    assert result.ok is False
    assert result.error == "no_search_results"
