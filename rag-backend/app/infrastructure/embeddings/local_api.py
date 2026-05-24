from math import isfinite

import httpx

from app.errors import NonRetryableIngestionError, RetryableIngestionError


class LocalApiEmbeddingProvider:
    def __init__(
        self,
        base_url: str,
        path: str,
        api_key: str,
        model: str,
        dimension: int,
        batch_size: int,
    ) -> None:
        if batch_size <= 0:
            raise NonRetryableIngestionError("Embedding batch size must be greater than zero.")
        if dimension <= 0:
            raise ValueError("Embedding dimension must be greater than zero.")

        self._base_url = base_url.rstrip("/")
        self._path = path if path.startswith("/") else f"/{path}"
        self._api_key = api_key
        self._model = model
        self._dimension = dimension
        self._batch_size = batch_size

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []

        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            embeddings.extend(self._embed_batch(batch))

        return embeddings

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            response = httpx.post(
                f"{self._base_url}{self._path}",
                json={"model": self._model, "input": texts},
                headers=headers,
                timeout=60.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429 or status_code >= 500:
                raise RetryableIngestionError("Embedding API request failed.") from exc

            raise NonRetryableIngestionError(f"Embedding API returned non-retryable HTTP {status_code}.") from exc
        except httpx.HTTPError as exc:
            raise RetryableIngestionError("Embedding API request failed.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise NonRetryableIngestionError("Embedding API response was not valid JSON.") from exc

        embeddings = self._parse_embeddings(payload)
        if len(embeddings) != len(texts):
            raise NonRetryableIngestionError(
                f"Embedding API expected {len(texts)} embeddings for the request batch, "
                f"but returned {len(embeddings)}."
            )

        return embeddings

    def _parse_embeddings(self, payload: object) -> list[list[float]]:
        if not isinstance(payload, dict):
            raise NonRetryableIngestionError("Embedding API response must be a JSON object.")

        raw_embeddings = payload.get("embeddings")
        if raw_embeddings is None and "data" in payload:
            data = payload["data"]
            if isinstance(data, list):
                raw_embeddings = []
                for item in data:
                    if not isinstance(item, dict) or "embedding" not in item:
                        raise NonRetryableIngestionError(
                            "Embedding API response data item did not include an embedding."
                        )
                    embedding = item["embedding"]
                    if not isinstance(embedding, list):
                        raise NonRetryableIngestionError("Embedding API response data item embedding must be a list.")
                    raw_embeddings.append(embedding)

        if not isinstance(raw_embeddings, list):
            raise NonRetryableIngestionError("Embedding API response did not include embeddings.")

        embeddings: list[list[float]] = []
        for vector in raw_embeddings:
            if not isinstance(vector, list):
                raise NonRetryableIngestionError("Embedding API returned a non-list embedding.")
            if len(vector) != self._dimension:
                raise NonRetryableIngestionError("Embedding API returned an unexpected dimension.")
            if any(
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not isfinite(float(value))
                for value in vector
            ):
                raise NonRetryableIngestionError("Embedding API returned a non-finite numeric value.")
            embeddings.append(vector)

        return embeddings

    def health_check(self) -> None:
        try:
            response = httpx.get(self._base_url, timeout=5.0)
        except httpx.HTTPError as exc:
            raise RetryableIngestionError("Embedding API health check failed.") from exc

        if response.status_code >= 500:
            raise RetryableIngestionError("Embedding API health check failed.")
