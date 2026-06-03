import re

from app.domain import QueryIntent

_SYNONYM_MAP: dict[str, list[str]] = {
    "重疾": ["重度疾病", "重大疾病", "大病"],
    "轻症": ["轻度疾病", "轻疾"],
    "身故": ["死亡", "身故保险金", "身故金"],
    "豁免": ["免交保费", "豁免保险费", "保费豁免"],
    "等待期": ["观察期"],
    "免责": ["责任免除", "不承担保险责任", "除外责任", "不赔"],
    "赔": ["给付", "保险金", "赔付", "赔偿"],
    "重疾险": ["重大疾病保险", "健康险"],
}

_INTENT_RULES: list[tuple[re.Pattern, QueryIntent]] = [
    (re.compile(r"花了.*万|花了.*元|花费.*元|费用.*赔|医疗费.*计算|能赔多少|算算|帮我算"), QueryIntent.CLAIM_CALCULATION),
    (re.compile(r"等待期|观察期|多少天.*等待|等待.*多久"), QueryIntent.WAITING_PERIOD),
    (re.compile(r"赔不赔|能赔吗|是否赔付|给付吗"), QueryIntent.BENEFIT_QUERY),
    (re.compile(r"赔多少|赔付比例|给付比例|保额|保险金额|赔几次|给付几次|每次.*赔|赔付.*多少"), QueryIntent.BENEFIT_QUERY),
    (re.compile(r"怎么赔|如何赔付|保险责任|保障范围|保障内容"), QueryIntent.BENEFIT_QUERY),
    (re.compile(r"算不算|属于.*重疾|属于.*轻症|属于.*疾病|疾病定义|什么.*算.*重疾|什么.*算.*轻症|定义"), QueryIntent.DISEASE_DEFINITION),
    (re.compile(r"原位癌|恶性肿瘤|轻症.*包括|重疾.*包括|病种"), QueryIntent.DISEASE_DEFINITION),
    (re.compile(r"免责|责任免除|不承担|不赔|除外|什么情况.*不赔|哪些.*不赔|酒驾|艾滋病|故意.*行为"), QueryIntent.EXCLUSION_QUERY),
    (re.compile(r"年龄|周岁|岁.*限制|多少岁|投保年龄"), QueryIntent.AGE_RULE),
    (re.compile(r"理赔|申请.*资料|需要.*材料|理赔.*资料|申请.*理赔"), QueryIntent.CLAIM_MATERIALS),
    (re.compile(r"对比|区别|哪个好|不同|差异"), QueryIntent.COMPARISON_QUERY),
    (re.compile(r"总结|概括|介绍|是什么|产品.*怎么样|保障.*什么"), QueryIntent.SUMMARY_QUERY),
]

_INTENT_CONTENT_TYPE_MAP: dict[QueryIntent, list[str]] = {
    QueryIntent.CLAIM_CALCULATION: ["insurance_liability", "clause"],
    QueryIntent.BENEFIT_QUERY: ["insurance_liability", "clause"],
    QueryIntent.DISEASE_DEFINITION: ["disease_definition", "definition", "table_candidate"],
    QueryIntent.EXCLUSION_QUERY: ["exclusion", "insurance_liability", "disease_definition"],
    QueryIntent.WAITING_PERIOD: ["waiting_period", "insurance_liability"],
    QueryIntent.AGE_RULE: ["age_rule", "insurance_liability", "clause"],
    QueryIntent.CLAIM_MATERIALS: ["claim_material", "clause"],
    QueryIntent.COMPARISON_QUERY: ["insurance_liability", "clause"],
    QueryIntent.SUMMARY_QUERY: ["insurance_liability", "clause"],
    QueryIntent.GENERAL: ["clause"],
}

_INTENT_SECTION_HINTS: dict[QueryIntent, list[str]] = {
    QueryIntent.CLAIM_CALCULATION: ["2.4", "2.5", "2.6", "10", "11", "13"],
    QueryIntent.WAITING_PERIOD: ["2.3", "7"],
    QueryIntent.EXCLUSION_QUERY: ["2.6"],
    QueryIntent.DISEASE_DEFINITION: ["10", "11", "13"],
    QueryIntent.CLAIM_MATERIALS: ["3.3"],
    QueryIntent.AGE_RULE: ["1.3", "2.5"],
}


def classify_intent(question: str) -> QueryIntent:
    for pattern, intent in _INTENT_RULES:
        if pattern.search(question):
            return intent
    return QueryIntent.GENERAL


def expand_synonyms(text: str) -> list[str]:
    expanded = [text]
    for word, synonyms in _SYNONYM_MAP.items():
        if word in text:
            for syn in synonyms:
                expanded.append(text.replace(word, syn))
    if len(expanded) > 5:
        expanded = expanded[:5]
    return expanded


def intent_summary(intent: QueryIntent) -> str:
    summaries = {
        QueryIntent.CLAIM_CALCULATION: "User is asking for a claim calculation with specific numbers.",
        QueryIntent.BENEFIT_QUERY: "User is asking about benefit amounts, payout ratios, or coverage scope.",
        QueryIntent.DISEASE_DEFINITION: "User is asking about disease classification or definition.",
        QueryIntent.EXCLUSION_QUERY: "User is asking about exclusions or non-covered scenarios.",
        QueryIntent.WAITING_PERIOD: "User is asking about waiting period or observation period.",
        QueryIntent.AGE_RULE: "User is asking about age-based rules or limits.",
        QueryIntent.CLAIM_MATERIALS: "User is asking about claim materials or application process.",
        QueryIntent.COMPARISON_QUERY: "User is comparing multiple products or clauses.",
        QueryIntent.SUMMARY_QUERY: "User is asking for a product summary or overview.",
        QueryIntent.GENERAL: "Use the original question as the retrieval query.",
    }
    return summaries.get(intent, summaries[QueryIntent.GENERAL])


def content_type_hints(intent: QueryIntent) -> list[str]:
    return _INTENT_CONTENT_TYPE_MAP.get(intent, _INTENT_CONTENT_TYPE_MAP[QueryIntent.GENERAL])


def section_hints(intent: QueryIntent) -> list[str]:
    return _INTENT_SECTION_HINTS.get(intent, [])
