import json
import re

from app.infrastructure.generators.base import AnswerGenerator
from app.observability import get_logger
from app.services.prompt_registry import get_default_prompt_registry

logger = get_logger(__name__)

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
    prompt = get_default_prompt_registry().render("rule_extraction", context=context).user
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
