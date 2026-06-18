from __future__ import annotations

import json

from app.search.query_planning import QueryPlanner
from app.search.schemas import SearchRequest


class StaticModel:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def generate(self, prompt: str, system_prompt: str | None = None) -> dict:
        return {"answer": json.dumps(self.payload, ensure_ascii=False)}


def test_colloquial_question_becomes_distinct_role_queries_and_preserves_entities():
    question = "你帮我看看平安人寿御享金越在2025年有没有新的\"现金价值表\"？"
    model = StaticModel(
        {
            "normalized_question": "查询平安人寿御享金越2025年最新现金价值表",
            "freshness": "recent",
            "source_preference": ["official"],
            "document_types": ["cash_value_table", "pdf"],
            "risk_level": "high",
            "protected_entities": ["平安人寿", "御享金越", "2025", "现金价值表"],
            "queries": [
                {"role": "official", "text": "平安人寿 御享金越 2025 官方 现金价值表"},
                {"role": "document", "text": "平安人寿 御享金越 2025 现金价值表 PDF"},
                {"role": "freshness", "text": "平安人寿 御享金越 2025 最新 现金价值表"},
            ],
        }
    )

    plan = QueryPlanner(model=model).plan(SearchRequest(original_question=question))

    assert plan.original_question == question
    assert plan.normalized_question != question
    assert 2 <= len(plan.queries) <= 4
    assert {query.role for query in plan.queries} == {"official", "document", "freshness"}
    assert len({query.text for query in plan.queries}) == len(plan.queries)
    for entity in ("平安人寿", "御享金越", "2025", "现金价值表"):
        assert entity in plan.protected_entities
        assert all(entity in query.text for query in plan.queries)


def test_invalid_model_queries_fall_back_without_copying_colloquial_question():
    question = "麻烦你给我查一下中国人寿鑫耀龙腾年金保险的官方条款在哪里？"
    model = StaticModel(
        {
            "normalized_question": question,
            "freshness": "not_required",
            "source_preference": ["official"],
            "document_types": ["clause"],
            "risk_level": "high",
            "protected_entities": ["中国人寿", "鑫耀龙腾"],
            "queries": [
                {"role": "official", "text": "另一个产品 官方"},
                {"role": "official", "text": "另一个产品 官方"},
            ],
        }
    )

    plan = QueryPlanner(model=model).plan(SearchRequest(original_question=question))

    assert 2 <= len(plan.queries) <= 4
    assert plan.normalized_question != question
    assert {query.role for query in plan.queries}.issuperset({"official", "document"})
    assert all("中国人寿" in query.text and "鑫耀龙腾" in query.text for query in plan.queries)
    assert all(query.text != question for query in plan.queries)


def test_latest_question_adds_freshness_and_regulatory_roles_conditionally():
    plan = QueryPlanner().plan(
        SearchRequest(original_question="金融监管总局最近关于人身险预定利率发布了什么通知？")
    )

    assert plan.network_requirement == "required"
    assert plan.freshness in {"latest", "recent"}
    assert plan.risk_level == "high"
    assert {query.role for query in plan.queries}.issuperset({"official", "document", "regulatory", "freshness"})
    assert len(plan.queries) == 4


def test_sensitive_identifiers_are_kept_only_in_original_question_not_provider_queries():
    question = "帮我用保单号PA123456789和手机号13800138000查询平安人寿御享金越条款"

    plan = QueryPlanner().plan(SearchRequest(original_question=question))

    assert plan.original_question == question
    assert all("PA123456789" not in query.text for query in plan.queries)
    assert all("13800138000" not in query.text for query in plan.queries)
    assert "PA123456789" not in plan.normalized_question
    assert "13800138000" not in plan.normalized_question


def test_high_risk_controls_provider_strategy_without_forcing_network_when_local_text_can_answer():
    plan = QueryPlanner().plan(SearchRequest(original_question="平安人寿御享金越条款中的等待期是多少？"))

    assert plan.risk_level == "high"
    assert plan.network_requirement == "conditional"
