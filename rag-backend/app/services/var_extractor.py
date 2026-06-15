import json
import re

from app.infrastructure.generators.base import AnswerGenerator
from app.observability import get_logger
from app.services.prompt_registry import get_default_prompt_registry

logger = get_logger(__name__)


def extract_user_vars(query: str, generator: AnswerGenerator) -> dict:
    try:
        prompt = get_default_prompt_registry().render("var_extraction", query=query).user
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
