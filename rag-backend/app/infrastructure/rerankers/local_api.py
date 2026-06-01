from math import isfinite

import httpx

from app.errors import NonRetryableIngestionError, RetryableIngestionError


class LocalApiReranker:
    def __init__(self, base_url: str, path: str, model: str, top_k: int) -> None:
        if top_k <= 0:
            raise ValueError("Rerank top_k must be greater than zero.")

        self._base_url = base_url.rstrip("/")
        self._path = path if path.startswith("/") else f"/{path}"
        self._model = model
        self._top_k = top_k

    def rerank(self, query: str, documents: list[str], top_k: int | None = None) -> list[dict]:
        if not documents:
            return []

        payload = {
            "query": query,
            "documents": documents,
            "model": self._model,
            "top_k": top_k or self._top_k,
        }
        try:
            response = httpx.post(f"{self._base_url}{self._path}", json=payload, timeout=60.0)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 429 or status_code >= 500:
                raise RetryableIngestionError("Rerank API request failed.") from exc
            raise NonRetryableIngestionError(f"Rerank API returned non-retryable HTTP {status_code}.") from exc
        except httpx.HTTPError as exc:
            raise RetryableIngestionError("Rerank API request failed.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise NonRetryableIngestionError("Rerank API response was not valid JSON.") from exc

        return self._parse_results(payload, documents)

    def _parse_results(self, payload: object, documents: list[str]) -> list[dict]:
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise NonRetryableIngestionError("Rerank API response did not include results.")

        results: list[dict] = []
        for item in payload["results"]:
            if not isinstance(item, dict):
                raise NonRetryableIngestionError("Rerank API returned an invalid result.")

            index = item.get("index")
            score = item.get("score")
            document = item.get("document")
            if (
                not isinstance(index, int)
                or index < 0
                or index >= len(documents)
                or isinstance(score, bool)
                or not isinstance(score, int | float)
                or not isfinite(float(score))
                or not isinstance(document, str)
            ):
                raise NonRetryableIngestionError("Rerank API returned an invalid result.")

            results.append({"index": index, "document": document, "score": float(score)})

        return results
