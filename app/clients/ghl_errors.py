class GHLError(Exception):
    """Base class for every failure at the GoHighLevel client boundary.

    Messages must never contain response bodies, headers, tokens or contact data.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GHLAuthenticationError(GHLError):
    """401/403: token rejected or missing a scope. Never retry."""


class GHLNotFoundError(GHLError):
    """404: the requested record does not exist. Never retry."""


class GHLRateLimitError(GHLError):
    """429: too many requests. Retryable, but only after waiting."""


class GHLTemporaryError(GHLError):
    """5xx, timeout or connection failure. Retryable with backoff."""


class GHLResponseError(GHLError):
    """GoHighLevel answered, but the response is malformed or unusable."""


class GHLAPIError(GHLError):
    """Any other unsuccessful response (e.g. 400, 422)."""
