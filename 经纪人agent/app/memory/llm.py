from __future__ import annotations
from typing import Callable

import httpx


class HTTPChatMemoryExtractor:
    def __init__(
        self,
        base_url: str,
        path: str,
        api_key: str,
        model: str,
        post: Callable[..., object] = httpx.post,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.path = path if path.startswith("/") else f"/{path}"
        self.api_key = api_key
        self.model = model
        self.post = post

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request_json = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
        }
        if tools is not None:
            request_json["tools"] = tools
        if tool_choice is not None:
            request_json["tool_choice"] = tool_choice

        response = self.post(
            f"{self.base_url}{self.path}",
            json=request_json,
            headers=headers,
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "answer": _extract_answer(payload),
            "tool_calls": _extract_tool_calls(payload),
            "tokens": payload.get("usage", {}) if isinstance(payload, dict) else {},
            "raw": payload,
        }


def build_memory_extractor_from_settings(settings: object) -> HTTPChatMemoryExtractor | None:
    base_url = str(getattr(settings, "llm_api_base_url", "") or "")
    model = str(getattr(settings, "llm_model", "") or "")
    if not base_url or not model:
        return None
    return HTTPChatMemoryExtractor(
        base_url=base_url,
        path=str(getattr(settings, "llm_api_path", "/chat/completions") or "/chat/completions"),
        api_key=str(getattr(settings, "llm_api_key", "") or getattr(settings, "minimax_api_key", "") or ""),
        model=model,
    )


def _extract_answer(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _extract_tool_calls(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return []
    first = choices[0]
    if not isinstance(first, dict):
        return []
    message = first.get("message")
    if not isinstance(message, dict):
        return []
    tool_calls = message.get("tool_calls")
    return tool_calls if isinstance(tool_calls, list) else []
