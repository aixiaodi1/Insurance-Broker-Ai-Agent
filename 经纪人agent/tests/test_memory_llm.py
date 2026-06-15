from app.memory.llm import HTTPChatMemoryExtractor


def test_http_chat_memory_extractor_uses_chat_completions_shape():
    calls = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": "{\"facts\": []}"}}],
                "usage": {"total_tokens": 12},
            }

    def fake_post(url: str, json: dict, headers: dict, timeout: object):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return Response()

    extractor = HTTPChatMemoryExtractor(
        base_url="https://llm.example",
        path="/chat/completions",
        api_key="key-1",
        model="model-1",
        post=fake_post,
    )

    result = extractor.generate("extract this", system_prompt="system")

    assert result["answer"] == "{\"facts\": []}"
    assert calls[0]["url"] == "https://llm.example/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer key-1"
    assert calls[0]["json"]["model"] == "model-1"
    assert calls[0]["json"]["messages"][0] == {"role": "system", "content": "system"}


def test_http_chat_memory_extractor_sends_tools_and_parses_tool_calls():
    calls = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "local_search",
                                        "arguments": '{"query":"MysteryCare"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"total_tokens": 12},
            }

    def fake_post(url: str, json: dict, headers: dict, timeout: object):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return Response()

    extractor = HTTPChatMemoryExtractor(
        base_url="https://llm.example",
        path="/chat/completions",
        api_key="key-1",
        model="model-1",
        post=fake_post,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "local_search",
                "description": "Search local files.",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        }
    ]

    result = extractor.generate("route this", tools=tools, tool_choice="auto")

    assert calls[0]["json"]["tools"] == tools
    assert calls[0]["json"]["tool_choice"] == "auto"
    assert result["tool_calls"][0]["function"]["name"] == "local_search"
