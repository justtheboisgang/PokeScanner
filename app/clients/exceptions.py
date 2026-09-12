"""Client exception hierarchy."""

from __future__ import annotations


class ClientError(Exception):
    """Base for all external-client errors."""


class RateLimitError(ClientError):
    """HTTP 429 that is retryable. `retry_after` in seconds if the API gave one."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class QuotaExceededError(ClientError):
    """HTTP 429 with code == 'quota_exceeded'.

    Do NOT retry (§4.2.5) — the monthly contingent is spent. Caller should alert.
    """
