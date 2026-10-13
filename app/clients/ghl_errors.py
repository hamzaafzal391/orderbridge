from typing import ClassVar


class GHLError(Exception):
    """Base class for every failure at the GoHighLevel client boundary.

    Messages must never contain response bodies, headers, tokens or contact data.
    """

    # Whether repeating the same request could succeed (see app/retry.py).
    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GHLAuthenticationError(GHLError):
    """401/403: token rejected or missing a scope. Never retry."""


class GHLNotFoundError(GHLError):
    """404: the requested record does not exist. Never retry."""


class GHLRateLimitError(GHLError):
    """429: too many requests. Retryable, but only after waiting."""

    retryable = True

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after  # seconds from the Retry-After header, if sent


class GHLTemporaryError(GHLError):
    """5xx, timeout or connection failure. Retryable with backoff."""

    retryable = True


class GHLResponseError(GHLError):
    """GoHighLevel answered, but the response is malformed or unusable."""


class GHLAPIError(GHLError):
    """Any other unsuccessful response (e.g. 400, 422)."""
