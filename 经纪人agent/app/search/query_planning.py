from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Protocol

from app.search.schemas import PlannedQuery, SearchPlan, SearchRequest


QUERY_ROLES = {"official", "document", "regulatory", "freshness"}
KNOWN_ENTITIES = (
    "国家金融监督管理总局",
    "金融监管总局",
    "中国银保监会",
    "银保监会",
    "平安人寿",
    "御享金越",
    "中国人寿",
    "鑫耀龙腾",
    "太平洋保险",
    "金生无忧",
    "泰康",
    "岁月有约",
)
COLLOQUIAL_PARTS = (
    "麻烦你",
    "请你",
    "你帮我",
    "帮我",
    "给我",
    "查一下",
    "查一查",
    "看一下",
    "看看",
    "我想知道",
)
LATEST_TERMS = ("最新", "最近", "当前", "现在", "今年", "新的", "新发布", "截至")
HIGH_RISK_TERMS = ("保险", "条款", "监管", "利率", "政策", "法律", "医疗", "金融")


class QueryPlanningModel(Protocol):
    def generate(self, prompt: str, system_prompt: str | None = None) -> dict: ...


class QueryPlanner:
    def __init__(self, model: QueryPlanningModel | None = None) -> None:
        self.model = model

    def plan(self, request: SearchRequest) -> SearchPlan:
        safe_request = SearchRequest(
            original_question=_redact_sensitive(request.original_question),
            query_goal=_redact_sensitive(request.query_goal),
            limit=request.limit,
        )
        entities = _extract_entities(safe_request.original_question)
        fallback = replace(_fallback_plan(safe_request, entities), original_question=request.original_question)
        if self.model is None:
            return fallback
        parsed = self._model_plan(safe_request, entities)
        return replace(parsed, original_question=request.original_question) if parsed else fallback

    def _model_plan(self, request: SearchRequest, entities: tuple[str, ...]) -> SearchPlan | None:
        try:
            response = self.model.generate(
                _planning_prompt(request, entities),
                system_prompt=(
                    "Rewrite a web-search request as strict JSON. Preserve protected entities exactly. "
                    "Return two to four distinct role queries and no prose."
                ),
            )
            payload = json.loads(str(response.get("answer") or ""))
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None

        model_entities = tuple(
            value
            for value in payload.get("protected_entities", [])
            if isinstance(value, str) and value and value in request.original_question
        )
        protected = _unique(entities + model_entities)
        normalized = _clean_query(str(payload.get("normalized_question") or ""))
        if not normalized or normalized == request.original_question.strip():
            return None

        queries: list[PlannedQuery] = []
        seen: set[str] = set()
        for row in payload.get("queries", []):
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or "")
            text = _clean_query(str(row.get("text") or ""))
            if role not in QUERY_ROLES or not text or text in seen:
                continue
            if any(entity not in text for entity in protected):
                continue
            suggested = tuple(term for term in row.get("model_suggested_terms", []) if isinstance(term, str))[:2]
            queries.append(PlannedQuery(role=role, text=text, model_suggested_terms=suggested))
            seen.add(text)
        if not 2 <= len(queries) <= 4:
            return None

        freshness = str(payload.get("freshness") or "not_required")
        if freshness not in {"not_required", "latest", "recent", "as_of"}:
            freshness = "not_required"
        risk_level = str(payload.get("risk_level") or "low")
        if risk_level not in {"low", "medium", "high"}:
            risk_level = "low"
        return SearchPlan(
            original_question=request.original_question,
            normalized_question=normalized,
            network_requirement=_network_requirement(request.original_question, freshness),
            freshness=freshness,
            source_preference=tuple(str(value) for value in payload.get("source_preference", []) if value),
            document_types=tuple(str(value) for value in payload.get("document_types", []) if value),
            risk_level=risk_level,
            protected_entities=protected,
            queries=tuple(queries),
        )


def _fallback_plan(request: SearchRequest, entities: tuple[str, ...]) -> SearchPlan:
    normalized = _normalize_question(request.original_question)
    freshness = "recent" if any(term in request.original_question for term in LATEST_TERMS) else "not_required"
    risk = "high" if any(term in request.original_question for term in HIGH_RISK_TERMS) else "low"
    document_types = _document_types(request.original_question)
    core = " ".join(entities) if entities else normalized
    topic = _topic_terms(normalized, entities)
    base = _clean_query(f"{core} {topic}")
    queries = [
        PlannedQuery(role="official", text=_clean_query(f"{base} 官方 官网")),
        PlannedQuery(role="document", text=_clean_query(f"{base} {_document_words(document_types)} PDF")),
    ]
    if "监管" in request.original_question or "金融监督管理总局" in request.original_question:
        queries.append(PlannedQuery(role="regulatory", text=_clean_query(f"{base} 金融监管总局 公告 通知")))
    if freshness != "not_required":
        queries.append(PlannedQuery(role="freshness", text=_clean_query(f"{base} 最新 发布")))
    return SearchPlan(
        original_question=request.original_question,
        normalized_question=normalized,
        network_requirement=_network_requirement(request.original_question, freshness),
        freshness=freshness,
        source_preference=("official", "regulator"),
        document_types=document_types,
        risk_level=risk,
        protected_entities=entities,
        queries=tuple(queries[:4]),
    )


def classify_search_requirement(question: str) -> dict[str, str]:
    plan = _fallback_plan(SearchRequest(original_question=question), _extract_entities(question))
    return {
        "mode": plan.network_requirement,
        "freshness": plan.freshness,
        "risk_level": plan.risk_level,
        "summary": "需要联网核验时效或高风险信息" if plan.network_requirement == "required" else "可根据已读取资料的充分性决定是否联网",
    }


def _planning_prompt(request: SearchRequest, entities: tuple[str, ...]) -> str:
    schema = {
        "normalized_question": "string",
        "freshness": "not_required|latest|recent|as_of",
        "source_preference": ["official"],
        "document_types": ["pdf"],
        "risk_level": "low|medium|high",
        "protected_entities": list(entities),
        "queries": [{"role": "official|document|regulatory|freshness", "text": "string"}],
    }
    return json.dumps(
        {"schema": schema, "original_question": request.original_question, "query_goal": request.query_goal},
        ensure_ascii=False,
    )


def _extract_entities(question: str) -> tuple[str, ...]:
    found = [entity for entity in KNOWN_ENTITIES if entity in question]
    for pattern in (r"[\"“](.+?)[\"”]", r"(?<!\d)((?:19|20)\d{2})(?:年)?", r"(?<!\d)(\d+(?:\.\d+)?%)"):
        found.extend(match.group(1) if match.lastindex else match.group(0) for match in re.finditer(pattern, question))
    return _unique(tuple(found))


def _normalize_question(question: str) -> str:
    normalized = question.strip()
    for part in COLLOQUIAL_PARTS:
        normalized = normalized.replace(part, "")
    normalized = re.sub(r"[？?！!，,。]", " ", normalized)
    normalized = re.sub(r"(?:有没有|在哪里|是什么|怎么样|吗)\s*$", "", normalized)
    return _clean_query(normalized)


def _topic_terms(normalized: str, entities: tuple[str, ...]) -> str:
    value = normalized
    for entity in entities:
        value = value.replace(entity, " ")
    return _clean_query(value)


def _document_types(question: str) -> tuple[str, ...]:
    mapping = (
        ("条款", "clause"),
        ("说明书", "product_manual"),
        ("信息披露", "disclosure"),
        ("公告", "notice"),
        ("费率", "rate_table"),
        ("现金价值", "cash_value_table"),
    )
    values = [value for term, value in mapping if term in question]
    return tuple(values or ["webpage"])


def _document_words(document_types: tuple[str, ...]) -> str:
    words = {
        "clause": "保险条款",
        "product_manual": "产品说明书",
        "disclosure": "信息披露",
        "notice": "公告",
        "rate_table": "费率表",
        "cash_value_table": "现金价值表",
        "webpage": "官方资料",
    }
    return " ".join(words.get(value, value) for value in document_types)


def _clean_query(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ，,。？?!！")


def _network_requirement(question: str, freshness: str) -> str:
    if freshness != "not_required":
        return "required"
    if any(term in question for term in ("官网", "官方", "监管", "公开信息", "联网", "网上")):
        return "required"
    return "conditional"


def _redact_sensitive(value: str) -> str:
    redacted = value
    redacted = re.sub(r"(?i)\b(?:fc-|sk-|bce-v3/)[A-Za-z0-9_./-]+", " ", redacted)
    redacted = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", " ", redacted)
    redacted = re.sub(r"(?<!\d)\d{17}[\dXx](?!\d)", " ", redacted)
    redacted = re.sub(r"(?:保单号|身份证号|证件号|手机号)\s*[:：]?\s*[A-Za-z0-9-]{6,}", " ", redacted)
    return _clean_query(redacted)


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
