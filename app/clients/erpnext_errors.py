class ERPNextError(Exception):
    """Base class for every failure at the ERPNext client boundary.

    Messages must never contain response bodies, headers, credentials or
    customer data.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ERPNextAuthenticationError(ERPNextError):
    """401/403: credentials rejected. Never retry; a human must fix them."""


class ERPNextNotFoundError(ERPNextError):
    """404: the requested record does not exist. Never retry."""


class ERPNextRateLimitError(ERPNextError):
    """429: too many requests. Retryable, but only after waiting."""


class ERPNextTemporaryError(ERPNextError):
    """5xx, timeout or connection failure. Retryable with backoff."""


class ERPNextResponseError(ERPNextError):
    """ERPNext answered, but the response is malformed or unexpected."""


class ERPNextAPIError(ERPNextError):
    """Any other unsuccessful response (e.g. 400, 409, 501)."""
