import re

import httpx

from app.errors import NonRetryableIngestionError, RetryableIngestionError


class MiniMaxGenerator:
    def __init__(self, base_url: str, path: str, api_key: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._path = path if path.startswith("/") else f"/{path}"
        self._api_key = api_key
        self._model = model

    def generate(self, prompt: str) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是严谨的中文 RAG 问答助手。只能依据用户提供的知识库上下文回答。"
                        "关键结论必须使用 [1]、[2] 这样的引用。资料不足时明确说明知识库中没有足够依据。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }

        try:
            response = httpx.post(
                f"{self._base_url}{self._path}",
                json=payload,
                headers=headers,
                timeout=httpx.Timeout(connect=5.0, read=90.0, write=10.0, pool=5.0),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429 or status_code >= 500:
                raise RetryableIngestionError("LLM API request failed.") from exc
            raise NonRetryableIngestionError(f"LLM API returned non-retryable HTTP {status_code}.") from exc
        except httpx.HTTPError as exc:
            raise RetryableIngestionError("LLM API request failed.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise NonRetryableIngestionError("LLM API response was not valid JSON.") from exc

        return self._parse_response(payload)

    def _parse_response(self, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise NonRetryableIngestionError("LLM API response must be a JSON object.")

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise NonRetryableIngestionError("LLM API response did not include an answer.")

        first = choices[0]
        if not isinstance(first, dict):
            raise NonRetryableIngestionError("LLM API response did not include an answer.")

        message = first.get("message")
        answer = message.get("content") if isinstance(message, dict) else first.get("text")
        if not isinstance(answer, str) or not answer.strip():
            raise NonRetryableIngestionError("LLM API response did not include an answer.")

        usage = payload.get("usage")
        tokens = {}
        if isinstance(usage, dict):
            tokens = {
                "prompt": int(usage.get("prompt_tokens") or 0),
                "completion": int(usage.get("completion_tokens") or 0),
                "total": int(usage.get("total_tokens") or 0),
            }

        return {"answer": _strip_thinking(answer), "tokens": tokens, "raw": payload}


def _strip_thinking(answer: str) -> str:
    return re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
