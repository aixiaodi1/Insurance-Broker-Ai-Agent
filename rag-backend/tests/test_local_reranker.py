import pytest

from app.errors import NonRetryableIngestionError, RetryableIngestionError
from app.infrastructure.rerankers.local_api import LocalApiReranker


def make_reranker() -> LocalApiReranker:
    return LocalApiReranker(
        base_url="http://rerank.local",
        path="/v1/rerank",
        model="reranker",
        top_k=2,
    )


def test_local_reranker_posts_query_documents_and_model(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://rerank.local/v1/rerank",
        json={
            "model": "reranker",
            "results": [
                {"index": 1, "document": "beta", "score": 0.9},
                {"index": 0, "document": "alpha", "score": 0.2},
            ],
        },
    )

    results = make_reranker().rerank("question", ["alpha", "beta"])

    request = httpx_mock.get_request()
    assert request is not None
    assert request.read().decode() == '{"query":"question","documents":["alpha","beta"],"model":"reranker","top_k":2}'
    assert results == [
        {"index": 1, "document": "beta", "score": 0.9},
        {"index": 0, "document": "alpha", "score": 0.2},
    ]


def test_local_reranker_allows_call_level_top_k(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://rerank.local/v1/rerank",
        json={"results": [{"index": 0, "document": "alpha", "score": 0.4}]},
    )

    make_reranker().rerank("question", ["alpha"], top_k=1)

    request = httpx_mock.get_request()
    assert request is not None
    assert '"top_k":1' in request.read().decode()


def test_local_reranker_treats_5xx_as_retryable(httpx_mock) -> None:
    httpx_mock.add_response(method="POST", url="http://rerank.local/v1/rerank", status_code=503)

    with pytest.raises(RetryableIngestionError, match="Rerank API request failed"):
        make_reranker().rerank("question", ["alpha"])


def test_local_reranker_treats_4xx_as_nonretryable(httpx_mock) -> None:
    httpx_mock.add_response(method="POST", url="http://rerank.local/v1/rerank", status_code=400)

    with pytest.raises(NonRetryableIngestionError, match="Rerank API returned non-retryable HTTP 400"):
        make_reranker().rerank("question", ["alpha"])


def test_local_reranker_rejects_invalid_payload(httpx_mock) -> None:
    httpx_mock.add_response(method="POST", url="http://rerank.local/v1/rerank", json={"results": [{"index": "bad"}]})

    with pytest.raises(NonRetryableIngestionError, match="invalid result"):
        make_reranker().rerank("question", ["alpha"])
