from app.domain import QueryIntent
from app.services.intent_classifier import classify_intent, expand_synonyms, intent_summary, content_type_hints


def test_classify_benefit_query() -> None:
    assert classify_intent("重疾赔多少？") == QueryIntent.BENEFIT_QUERY
    assert classify_intent("赔付比例是多少") == QueryIntent.BENEFIT_QUERY
    assert classify_intent("轻症赔几次？") == QueryIntent.BENEFIT_QUERY
    assert classify_intent("保障范围是什么") == QueryIntent.BENEFIT_QUERY
    assert classify_intent("酒驾赔不赔？") == QueryIntent.BENEFIT_QUERY
    assert classify_intent("原位癌赔不赔？") == QueryIntent.BENEFIT_QUERY
    assert classify_intent("艾滋病赔不赔？") == QueryIntent.BENEFIT_QUERY


def test_classify_disease_definition() -> None:
    assert classify_intent("原位癌算不算轻症？") == QueryIntent.DISEASE_DEFINITION
    assert classify_intent("恶性肿瘤重度包括哪些") == QueryIntent.DISEASE_DEFINITION
    assert classify_intent("疾病定义是什么") == QueryIntent.DISEASE_DEFINITION


def test_classify_exclusion_query() -> None:
    assert classify_intent("责任免除包括哪些") == QueryIntent.EXCLUSION_QUERY
    assert classify_intent("什么情况不赔") == QueryIntent.EXCLUSION_QUERY
    assert classify_intent("免责条款有哪几条") == QueryIntent.EXCLUSION_QUERY
    assert classify_intent("除外责任是什么") == QueryIntent.EXCLUSION_QUERY


def test_classify_waiting_period() -> None:
    assert classify_intent("等待期是多少天？") == QueryIntent.WAITING_PERIOD
    assert classify_intent("观察期多久") == QueryIntent.WAITING_PERIOD


def test_classify_age_rule() -> None:
    assert classify_intent("投保年龄限制是多少？") == QueryIntent.AGE_RULE
    assert classify_intent("年龄规定") == QueryIntent.AGE_RULE
    assert classify_intent("多少岁可以投保") == QueryIntent.AGE_RULE


def test_classify_claim_materials() -> None:
    assert classify_intent("申请理赔需要什么资料？") == QueryIntent.CLAIM_MATERIALS
    assert classify_intent("理赔需要哪些材料") == QueryIntent.CLAIM_MATERIALS


def test_classify_summary_query() -> None:
    assert classify_intent("这个产品保障什么") == QueryIntent.SUMMARY_QUERY
    assert classify_intent("介绍一下这个产品") == QueryIntent.SUMMARY_QUERY


def test_classify_general_query() -> None:
    assert classify_intent("今天天气怎么样") == QueryIntent.GENERAL
    assert classify_intent("你好") == QueryIntent.GENERAL


def test_synonym_expansion_keeps_original() -> None:
    expanded = expand_synonyms("重疾赔多少")
    assert "重疾赔多少" in expanded


def test_synonym_expansion_adds_variants() -> None:
    expanded = expand_synonyms("重疾赔付")
    assert any("重度疾病" in e for e in expanded) or any("重大疾病" in e for e in expanded)


def test_synonym_expansion_limited() -> None:
    expanded = expand_synonyms("重疾轻症身故豁免等待期免责")
    assert len(expanded) <= 5


def test_synonym_expansion_no_match() -> None:
    expanded = expand_synonyms("hello world")
    assert expanded == ["hello world"]


def test_intent_summary_returns_string() -> None:
    for intent in QueryIntent:
        summary = intent_summary(intent)
        assert isinstance(summary, str)
        assert len(summary) > 0


def test_content_type_hints_returns_list() -> None:
    for intent in QueryIntent:
        hints = content_type_hints(intent)
        assert isinstance(hints, list)
        assert len(hints) > 0
