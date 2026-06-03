import json
import re

from app.infrastructure.generators.base import AnswerGenerator
from app.observability import get_logger

logger = get_logger(__name__)

_RULE_EXTRACTION_PROMPT = (
    "你是一个保险条款分析专家。请从以下知识库资料中抽取理赔计算相关的结构化规则。\n\n"
    "如果没有找到任何计算规则，返回空列表 []。\n\n"
    "请严格按以下 JSON Schema 返回一个数组（即使只有一条规则也要用数组包装）：\n"
    '{{\n'
    '  "rule_type": "medical_reimbursement" 或 "fixed_benefit" 或 "unknown",\n'
    '  "formula": "自然语言描述的计算公式",\n'
    '  "formula_expr": "带变量名的公式表达式，如 (eligible_expense - deductible) * reimbursement_ratio",\n'
    '  "required_vars": ["变量名1", "变量名2"],\n'
    '  "optional_vars": ["变量名1"],\n'
    '  "limits": {{"annual_limit": null, "single_limit": null, "notes": ""}},\n'
    '  "evidence": [{{"chunk_id": "来源ID", "text": "原文片段"}}]\n'
    '}}\n\n'
    "可用的标准变量名：\n"
    "- medical_expense: 医疗费用金额\n"
    "- eligible_expense: 可赔费用金额\n"
    "- deductible: 免赔额\n"
    "- reimbursement_ratio: 赔付比例（小数，如 1.0 表示 100%）\n"
    "- social_insurance_used: 是否经社保结算（true/false）\n"
    "- annual_limit: 年度限额\n"
    "- single_limit: 单次限额\n"
    "- hospital_level: 医院等级\n"
    "- disease_name: 疾病名称\n"
    "- claim_type: 理赔类型\n\n"
    "知识库资料：\n{context}"
)

_KNOWN_VAR_NAMES = {
    "medical_expense", "eligible_expense", "deductible",
    "reimbursement_ratio", "social_insurance_used",
    "annual_limit", "single_limit", "hospital_level",
    "disease_name", "claim_type",
}

_DEFAULT_RULE = {
    "rule_type": "unknown",
    "formula": "",
    "formula_expr": "",
    "required_vars": [],
    "optional_vars": [],
    "limits": {},
    "evidence": [],
}


def extract_rules(context: str, generator: AnswerGenerator) -> list[dict]:
    prompt = _RULE_EXTRACTION_PROMPT.format(context=context)
    try:
        result = generator.generate(prompt)
        answer = str(result.get("answer", ""))
        json_str = _extract_json(answer)
        if json_str is None:
            logger.warning("rule_extractor_no_json", extra={"extra_fields": {"answer_preview": answer[:200]}})
            return [_DEFAULT_RULE]
        parsed = json.loads(json_str)
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            return [_DEFAULT_RULE]
        for rule in parsed:
            _normalize_rule(rule)
        return parsed
    except Exception as exc:
        logger.warning("rule_extractor_failed", extra={"extra_fields": {"error": str(exc)}})
        return [_DEFAULT_RULE]


def _extract_json(text: str) -> str | None:
    text = text.strip()
    for pattern in [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```", r"(\[.*\])", r"(\{.*\})"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def _normalize_rule(rule: dict) -> None:
    for key in ("required_vars", "optional_vars"):
        if key not in rule:
            rule[key] = []
        elif isinstance(rule[key], list):
            rule[key] = [v for v in rule[key] if isinstance(v, str) and v in _KNOWN_VAR_NAMES]


def get_all_required_vars(rules: list[dict]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for rule in rules:
        for v in rule.get("required_vars", []):
            if isinstance(v, str) and v not in seen:
                seen.add(v)
                result.append(v)
    return result
