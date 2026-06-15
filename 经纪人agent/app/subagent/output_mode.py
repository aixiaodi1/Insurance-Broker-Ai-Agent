from __future__ import annotations

_OUTPUT_MODE_HINTS: dict[str, str] = {
    "gpt-4o": "json_schema",
    "gpt-4o-mini": "json_schema",
    "gpt-4": "function_calling",
    "gpt-4-turbo": "json_schema",
    "claude-sonnet-4-5": "json_schema",
    "claude-haiku-4-5": "json_schema",
    "claude-sonnet-4": "json_schema",
    "claude-haiku-4": "json_schema",
    "claude-3-opus": "function_calling",
    "claude-3-sonnet": "function_calling",
    "claude-3-haiku": "function_calling",
    "gemini-2.0-flash": "json_schema",
    "gemini-2.0-pro": "json_schema",
    "gemini-1.5-pro": "function_calling",
    "deepseek-chat": "json_schema",
    "deepseek-reasoner": "function_calling",
}


def resolve_output_mode(model: str, configured_mode: str) -> str:
    if configured_mode != "auto":
        return configured_mode
    for key, mode in _OUTPUT_MODE_HINTS.items():
        if key in model:
            return mode
    return "function_calling"


def build_request_kwargs(
    output_mode: str,
    schema: dict | None,
    temperature: float,
) -> dict:
    kwargs: dict = {"temperature": temperature}

    if output_mode == "json_schema" and schema is not None:
        kwargs["response_format"] = {
            "type": "json_object",
        }
    elif output_mode == "function_calling" and schema is not None:
        func_name = "format_result"
        kwargs["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": func_name,
                    "description": "Format the result according to the required schema",
                    "parameters": schema,
                },
            }
        ]
        kwargs["tool_choice"] = {"type": "function", "function": {"name": func_name}}

    return kwargs
