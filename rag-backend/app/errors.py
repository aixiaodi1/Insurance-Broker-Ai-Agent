class RagBackendError(Exception):
    """Base exception for expected RAG backend failures."""


class ValidationError(RagBackendError):
    """Raised when user input cannot be accepted."""


class RetryableIngestionError(RagBackendError):
    """Raised when RQ should retry the ingestion job."""


class NonRetryableIngestionError(RagBackendError):
    """Raised when retrying cannot fix the ingestion job."""
