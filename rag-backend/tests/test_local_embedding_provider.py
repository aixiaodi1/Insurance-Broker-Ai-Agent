import httpx
import pytest

from app.errors import NonRetryableIngestionError
from app.infrastructure.embeddings.local_api import LocalApiEmbeddingProvider


def test_local_embedding_provider_reads_key_and_validates_dimension(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]},
    )
    provider = LocalApiEmbeddingProvider(
        base_url="http://localhost:9000",
        path="/v1/embeddings",
        api_key="secret",
        model="embo-01",
        dimension=3,
        batch_size=32,
    )

    embeddings = provider.embed_texts(["alpha", "beta"])
    request = httpx_mock.get_request()

    assert embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert isinstance(request, httpx.Request)
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.read() == b'{"model":"embo-01","input":["alpha","beta"]}'


def test_local_embedding_provider_accepts_embeddings_response_shape(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"embeddings": [[0.1, 0.2, 0.3]]},
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    assert provider.embed_texts(["alpha"]) == [[0.1, 0.2, 0.3]]


def test_local_embedding_provider_rejects_dimension_mismatch(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"embeddings": [[0.1, 0.2]]},
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    with pytest.raises(NonRetryableIngestionError):
        provider.embed_texts(["alpha"])


@pytest.mark.parametrize(
    ("texts", "embeddings"),
    [
        (["alpha", "beta"], [[0.1, 0.2, 0.3]]),
        (["alpha"], [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]),
    ],
)
def test_local_embedding_provider_rejects_response_count_mismatch(httpx_mock, texts, embeddings) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"embeddings": embeddings},
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    with pytest.raises(NonRetryableIngestionError, match="expected.*embedding"):
        provider.embed_texts(texts)


def test_local_embedding_provider_rejects_invalid_json_response(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        text="{not json",
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    with pytest.raises(NonRetryableIngestionError, match="valid JSON"):
        provider.embed_texts(["alpha"])


def test_local_embedding_provider_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError, match="dimension"):
        LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 0, 32)


def test_local_embedding_provider_rejects_missing_embeddings_shape(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"items": []},
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    with pytest.raises(NonRetryableIngestionError):
        provider.embed_texts(["alpha"])


def test_local_embedding_provider_rejects_data_item_missing_embedding(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"data": [{"not_embedding": [0.1, 0.2, 0.3]}]},
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    with pytest.raises(NonRetryableIngestionError, match="data item.*embedding"):
        provider.embed_texts(["alpha"])


@pytest.mark.parametrize(
    "bad_value",
    ["0.2", True, float("nan")],
)
def test_local_embedding_provider_rejects_non_finite_numeric_values(httpx_mock, bad_value) -> None:
    if isinstance(bad_value, float) and bad_value != bad_value:
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:9000/v1/embeddings",
            text='{"embeddings": [[0.1, NaN, 0.3]]}',
        )
    else:
        httpx_mock.add_response(
            method="POST",
            url="http://localhost:9000/v1/embeddings",
            json={"embeddings": [[0.1, bad_value, 0.3]]},
        )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    with pytest.raises(NonRetryableIngestionError, match="finite numeric"):
        provider.embed_texts(["alpha"])


def test_local_embedding_provider_accepts_mixed_int_and_float_values(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"embeddings": [[1, 0.2, -3.5]]},
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    assert provider.embed_texts(["alpha"]) == [[1, 0.2, -3.5]]


def test_local_embedding_provider_rejects_infinite_values(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        text='{"embeddings": [[0.1, Infinity, 0.3]]}',
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    with pytest.raises(NonRetryableIngestionError, match="finite numeric"):
        provider.embed_texts(["alpha"])


def test_local_embedding_provider_batches_requests_and_normalizes_url(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"embeddings": [[0.1], [0.2]]},
    )
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"embeddings": [[0.3]]},
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000/", "v1/embeddings", "", "embo-01", 1, 2)

    assert provider.embed_texts(["alpha", "beta", "gamma"]) == [[0.1], [0.2], [0.3]]
    assert [request.read() for request in httpx_mock.get_requests()] == [
        b'{"model":"embo-01","input":["alpha","beta"]}',
        b'{"model":"embo-01","input":["gamma"]}',
    ]


def test_local_embedding_provider_omits_auth_header_when_key_is_empty(httpx_mock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:9000/v1/embeddings",
        json={"embeddings": [[0.1, 0.2, 0.3]]},
    )
    provider = LocalApiEmbeddingProvider("http://localhost:9000", "/v1/embeddings", "", "embo-01", 3, 32)

    provider.embed_texts(["alpha"])

    assert "Authorization" not in httpx_mock.get_request().headers
