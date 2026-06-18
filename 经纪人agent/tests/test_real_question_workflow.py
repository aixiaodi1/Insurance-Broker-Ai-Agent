from __future__ import annotations

import os

import pytest

from app.search.orchestrator import SearchOrchestrator
from app.search.providers import BaiduBrowserSearchProvider, BaiduQianfanSearchProvider, FirecrawlSearchProvider
from app.search.query_planning import QueryPlanner
from app.search.schemas import SearchItem, SearchProviderResult, SearchRequest
from app.web_acquisition.http_fetcher import FastHttpFetcher
from app.web_acquisition.schemas import AcquisitionResult, AcquisitionStep


REAL_ACCEPTANCE_QUESTIONS = [
    "平安人寿御享金越保险条款 PDF 在哪里？",
    "中国人寿鑫耀龙腾年金保险的官方产品资料和条款是什么？",
    "太平洋保险金生无忧重疾险是否有官方条款或信息披露页面？",
    "国家金融监督管理总局最近关于人身险预定利率的公开信息是什么？",
    "泰康岁月有约养老年金保险有没有官方说明书或条款下载？",
]


class LoopProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []

    def search(self, query: str, limit: int = 8) -> SearchProviderResult:
        self.calls.append(query)
        slug = str(abs(hash(query)))
        return SearchProviderResult(
            provider=self.name,
            ok=True,
            results=[
                SearchItem(
                    title=f"{query} 官方文件",
                    url=f"https://official.example/{slug}.pdf",
                    snippet=f"{query} 正式发布内容",
                    provider=self.name,
                    rank=1,
                )
            ],
        )


class LoopFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch(self, url: str, goal: str, allowed_domains=None) -> AcquisitionResult:
        self.calls.append(url)
        return AcquisitionResult(
            success=True,
            input_url=url,
            final_url=url,
            strategy_used="http",
            title="官方文件",
            text=f"已读取与问题相关的官方正文：{goal}",
            steps=[AcquisitionStep(layer="http", action="fetch", description="Fetched candidate URL")],
        )


def _run_codex_style_loop(orchestrator: SearchOrchestrator, fetcher: LoopFetcher, question: str) -> dict:
    search = orchestrator.search(SearchRequest(original_question=question, limit=8))
    stages = [event["type"] for event in search.public_trace]
    sources = []
    for candidate in search.results[:8]:
        stages.append("source_fetch_started")
        fetched = fetcher.fetch(candidate.url, question)
        stages.append("source_fetch_finished")
        if fetched.success and fetched.text:
            sources.append({"url": fetched.final_url, "text": fetched.text, "title": fetched.title})
    citations = [source["url"] for source in sources]
    if citations:
        stages.append("citation_selected")
    answer = f"根据已读取的官方来源回答。[1]({citations[0]})" if citations else ""
    return {"search": search, "sources": sources, "citations": citations, "answer": answer, "stages": stages}


def test_five_real_questions_complete_codex_style_search_loop():
    baidu = LoopProvider("baidu_qianfan")
    firecrawl = LoopProvider("firecrawl")
    orchestrator = SearchOrchestrator(
        planner=QueryPlanner(),
        primary=baidu,
        fallback=firecrawl,
        browser=LoopProvider("baidu_browser"),
        resolve_host=lambda host: ["93.184.216.34"],
        trusted_domains={"official.example"},
    )
    fetcher = LoopFetcher()
    required_stages = {
        "query_plan_ready",
        "provider_search_started",
        "provider_search_finished",
        "search_fused",
        "source_fetch_started",
        "source_fetch_finished",
        "citation_selected",
    }

    for question in REAL_ACCEPTANCE_QUESTIONS:
        outcome = _run_codex_style_loop(orchestrator, fetcher, question)
        plan = outcome["search"].plan
        missing = required_stages.difference(outcome["stages"])

        assert plan is not None, f"query planning missing: {question}"
        assert plan.original_question == question
        assert 2 <= len(plan.queries) <= 4, f"invalid query count: {question}"
        assert len({query.text for query in plan.queries}) == len(plan.queries), f"duplicate queries: {question}"
        assert outcome["search"].results, f"no fused candidates: {question}"
        assert outcome["sources"], f"no readable source body: {question}"
        assert outcome["citations"], f"no final citations: {question}"
        assert outcome["answer"], f"no cited answer: {question}"
        assert not missing, f"missing observable stages {sorted(missing)}: {question}"

    assert baidu.calls
    assert firecrawl.calls
    assert fetcher.calls


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_SEARCH_TESTS") != "1"
    or not os.getenv("BAIDU_QIANFAN_API_KEY")
    or not os.getenv("FIRECRAWL_API_KEY"),
    reason="Set RUN_LIVE_SEARCH_TESTS=1 plus rotated Baidu and Firecrawl server-side keys.",
)
def test_live_real_questions_search_open_and_read_sources():
    orchestrator = SearchOrchestrator(
        planner=QueryPlanner(),
        primary=BaiduQianfanSearchProvider(
            api_key=os.getenv("BAIDU_QIANFAN_API_KEY", ""),
            endpoint=os.getenv("BAIDU_QIANFAN_SEARCH_ENDPOINT", "https://qianfan.baidubce.com/v2/ai_search/web_search"),
        ),
        fallback=FirecrawlSearchProvider(
            api_key=os.getenv("FIRECRAWL_API_KEY", ""),
            endpoint=os.getenv("FIRECRAWL_SEARCH_ENDPOINT", "https://api.firecrawl.dev/v2/search"),
        ),
        browser=BaiduBrowserSearchProvider(),
    )
    fetcher = FastHttpFetcher()

    for question in REAL_ACCEPTANCE_QUESTIONS:
        search = orchestrator.search(SearchRequest(original_question=question, limit=8))
        assert search.results, f"no live search candidates: {question}; errors={search.errors}"
        readable = [fetcher.fetch(item.url, question) for item in search.results[:8]]
        assert any(result.success and result.text for result in readable), f"no readable live source: {question}"
