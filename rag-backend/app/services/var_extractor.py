import json
import re

from app.infrastructure.generators.base import AnswerGenerator
from app.observability import get_logger

logger = get_logger(__name__)

_VAR_EXTRACTION_PROMPT = (
    "你是一个保险理赔信息提取助手。请从用户输入中提取保险理赔相关的变量信息。\n\n"
    "请严格按以下 JSON Schema 返回：\n"
    '{{\n'
    '  "medical_expense": number | null,\n'
    '  "eligible_expense": number | null,\n'
    '  "deductible": number | null,\n'
    '  "reimbursement_ratio": number | null,\n'
    '  "social_insurance_used": boolean | null,\n'
    '  "annual_limit": number | null,\n'
    '  "single_limit": number | null,\n'
    '  "hospital_level": string | null,\n'
    '  "disease_name": string | null,\n'
    '  "claim_type": string | null\n'
    '}}\n\n'
    "说明：\n"
    "- 赔付比例 100% 表示为 1.0，80% 表示为 0.8\n"
    "- 6万表示为 60000，5千表示为 5000\n"
    "- 如果输入中没有该变量的值，设为 null\n"
    "- 只提取用户明确提供的信息，不要猜测\n\n"
    "用户输入：{query}"
)


def extract_user_vars(query: str, generator: AnswerGenerator) -> dict:
    try:
        prompt = _VAR_EXTRACTION_PROMPT.format(query=query)
        result = generator.generate(prompt)
        answer = str(result.get("answer", ""))
        json_str = _extract_json(answer)
        if json_str is None:
            logger.warning("var_extractor_no_json", extra={"extra_fields": {"answer_preview": answer[:200]}})
            return {}
        parsed = json.loads(json_str)
        if not isinstance(parsed, dict):
            return {}
        return {k: v for k, v in parsed.items() if v is not None}
    except Exception as exc:
        logger.warning("var_extractor_failed", extra={"extra_fields": {"error": str(exc)}})
        return {}


def _extract_json(text: str) -> str | None:
    text = text.strip()
    for pattern in [r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```", r"(\{.*\})"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
    return None
