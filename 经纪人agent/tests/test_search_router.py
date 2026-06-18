from __future__ import annotations

from app.search.router import SearchRouter, looks_high_risk_query
from app.search.schemas import SearchItem, SearchProviderResult


class FakeProvider:
    def __init__(self, name: str, results: list[SearchItem] | None = None, error: str | None = None) -> None:
        self.name = name
        self.results = results or []
        self.error = error
        self.calls: list[str] = []

    def search(self, query: str, limit: int = 8) -> SearchProviderResult:
        self.calls.append(query)
        if self.error:
            return SearchProviderResult(provider=self.name, ok=False, results=[], error=self.error)
        return SearchProviderResult(provider=self.name, ok=True, results=self.results[:limit])


def item(url: str, provider: str = "baidu", title: str = "Title") -> SearchItem:
    return SearchItem(title=title, url=url, snippet="snippet", provider=provider, rank=1)


def test_router_uses_baidu_first_and_brave_fallback_when_primary_fails():
    baidu = FakeProvider("baidu_qianfan", error="timeout")
    brave = FakeProvider("brave", [item("https://example.com/official.pdf", provider="brave")])
    router = SearchRouter(primary=baidu, fallback=brave, resolve_host=lambda host: ["93.184.216.34"])

    result = router.search("普通问题", limit=5)

    assert result.provider_used == "brave"
    assert result.fallback_used is True
    assert [row.url for row in result.results] == ["https://example.com/official.pdf"]
    assert baidu.calls == ["普通问题"]
    assert brave.calls == ["普通问题"]


def test_high_risk_query_uses_baidu_and_brave_then_deduplicates_and_reranks():
    baidu = FakeProvider(
        "baidu_qianfan",
        [
            item("https://baijiahao.baidu.com/s?id=1", title="营销解读"),
            item("https://example.com/clause.pdf", title="官方条款"),
        ],
    )
    brave = FakeProvider(
        "brave",
        [
            item("https://example.com/clause.pdf", provider="brave", title="Official Clause"),
            item("https://www.cbirc.gov.cn/doc.html", provider="brave", title="监管公告"),
        ],
    )
    router = SearchRouter(primary=baidu, fallback=brave, resolve_host=lambda host: ["93.184.216.34"])

    result = router.search("平安人寿御享金越保险条款 PDF 在哪里？", limit=5)

    assert result.provider_used == "baidu_qianfan+brave"
    assert baidu.calls and brave.calls
    assert len({row.url for row in result.results}) == len(result.results)
    assert result.results[0].trust_tier in {"regulator", "official", "official_document"}
    assert any("seo_or_marketing_risk" in row.risk_flags for row in result.results)


def test_router_rejects_search_results_that_fail_security_gate():
    baidu = FakeProvider(
        "baidu_qianfan",
        [
            item("http://127.0.0.1/admin"),
            item("https://example.com/official.pdf"),
        ],
    )
    brave = FakeProvider("brave", [])
    router = SearchRouter(primary=baidu, fallback=brave, resolve_host=lambda host: ["93.184.216.34"])

    result = router.search("普通问题", limit=5)

    assert [row.url for row in result.results] == ["https://example.com/official.pdf"]
    assert result.errors[0]["code"] in {"host_not_allowed", "ip_not_allowed"}


def test_five_real_acceptance_questions_are_treated_as_high_risk():
    questions = [
        "平安人寿御享金越保险条款 PDF 在哪里？",
        "中国人寿鑫耀龙腾年金保险的官方产品资料和条款是什么？",
        "太平洋保险金生无忧重疾险是否有官方条款或信息披露页面？",
        "国家金融监督管理总局最近关于人身险预定利率的公开信息是什么？",
        "泰康岁月有约养老年金保险有没有官方说明书或条款下载？",
    ]

    assert all(looks_high_risk_query(question) for question in questions)
