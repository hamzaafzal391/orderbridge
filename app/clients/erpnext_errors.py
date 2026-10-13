from typing import ClassVar


class ERPNextError(Exception):
    """Base class for every failure at the ERPNext client boundary.

    Messages must never contain response bodies, headers, credentials or
    customer data.
    """

    # Whether repeating the same request could succeed (see app/retry.py).
    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ERPNextAuthenticationError(ERPNextError):
    """401/403: credentials rejected. Never retry; a human must fix them."""


class ERPNextNotFoundError(ERPNextError):
    """404: the requested record does not exist. Never retry."""


class ERPNextRateLimitError(ERPNextError):
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


class ERPNextTemporaryError(ERPNextError):
    """5xx, timeout or connection failure. Retryable with backoff."""

    retryable = True


class ERPNextResponseError(ERPNextError):
    """ERPNext answered, but the response is malformed or unexpected."""


class ERPNextAPIError(ERPNextError):
    """Any other unsuccessful response (e.g. 400, 409, 501)."""
