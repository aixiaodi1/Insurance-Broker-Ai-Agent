import pytest

from app.errors import NonRetryableIngestionError, RetryableIngestionError
from app.infrastructure.generators.minimax import MiniMaxGenerator


def make_generator() -> MiniMaxGenerator:
    return MiniMaxGenerator(
        base_url="https://api.minimax.io/v1",
        path="/chat/completions",
        api_key="secret",
        model="MiniMax-M2.7",
    )


def test_minimax_generator_posts_openai_compatible_chat_request(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api.minimax.io/v1/chat/completions",
        json={
            "choices": [{"message": {"content": "Answer with citation. [1]"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
        },
    )

    result = make_generator().generate("Use context.")

    request = httpx_mock.get_request()
    assert request is not None
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.headers["Content-Type"] == "application/json"
    body = request.read().decode()
    assert '"model":"MiniMax-M2.7"' in body
    assert '"content":"Use context."' in body
    assert result == {
        "answer": "Answer with citation. [1]",
        "tokens": {"prompt": 7, "completion": 5, "total": 12},
        "raw": {
            "choices": [{"message": {"content": "Answer with citation. [1]"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
        },
    }


def test_minimax_generator_treats_5xx_as_retryable(httpx_mock) -> None:
    httpx_mock.add_response(method="POST", url="https://api.minimax.io/v1/chat/completions", status_code=500)

    with pytest.raises(RetryableIngestionError, match="LLM API request failed"):
        make_generator().generate("Use context.")


def test_minimax_generator_treats_4xx_as_nonretryable(httpx_mock) -> None:
    httpx_mock.add_response(method="POST", url="https://api.minimax.io/v1/chat/completions", status_code=401)

    with pytest.raises(NonRetryableIngestionError, match="LLM API returned non-retryable HTTP 401"):
        make_generator().generate("Use context.")


def test_minimax_generator_rejects_missing_answer(httpx_mock) -> None:
    httpx_mock.add_response(method="POST", url="https://api.minimax.io/v1/chat/completions", json={"choices": []})

    with pytest.raises(NonRetryableIngestionError, match="LLM API response did not include an answer"):
        make_generator().generate("Use context.")


def test_minimax_generator_strips_thinking_blocks(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="https://api.minimax.io/v1/chat/completions",
        json={"choices": [{"message": {"content": "<think>internal reasoning</think>\n\n连接成功。"}}]},
    )

    result = make_generator().generate("Use context.")

    assert result["answer"] == "连接成功。"
