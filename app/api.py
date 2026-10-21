"""The web front door: receives "deal won" messages from a GoHighLevel workflow.

Thin on purpose: it authenticates the caller, validates the message, hands it to
`handle_deal_won` and translates the outcome into an HTTP answer. Answers never contain customer
data, emails, secrets or exception text.

Run with: python -m app serve
"""

import hmac
import logging
import math
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from app.clients.erpnext import ERPNextClient
from app.clients.erpnext_errors import ERPNextRateLimitError, ERPNextTemporaryError
from app.clients.ghl import GHLClient
from app.clients.ghl_errors import GHLRateLimitError, GHLTemporaryError
from app.config import Settings, get_settings
from app.db.repository import Repository
from app.db.session import engine_from_settings, make_sessionmaker
from app.services.customer_matching import ContactSource
from app.services.customer_sync import ERPCustomers
from app.services.deal_won import DealWonEvent, handle_deal_won

logger = logging.getLogger("orderbridge")

# Opens the two clients for one request and closes them afterwards. Tests pass fakes instead.
Clients = Callable[[], AbstractContextManager[tuple[ContactSource, ERPCustomers]]]

TEMPORARY_ERRORS = (
    GHLTemporaryError,
    GHLRateLimitError,
    ERPNextTemporaryError,
    ERPNextRateLimitError,
)


# A short secret is easy to guess, so the server refuses to start with one.
MIN_SECRET_LENGTH = 16


class ConfigurationError(Exception):
    """The webhook server cannot start because required settings are missing."""


@contextmanager
def real_clients(settings: Settings) -> Iterator[tuple[ContactSource, ERPCustomers]]:
    with GHLClient(settings) as contacts, ERPNextClient(settings) as customers:
        yield contacts, customers


def create_app(
    settings: Settings | None = None,
    *,
    repository: Repository | None = None,
    clients: Clients | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    secret = settings.webhook_secret.get_secret_value() if settings.webhook_secret else ""
    problems = []
    if len(secret) < MIN_SECRET_LENGTH:
        problems.append(f"webhook_secret (at least {MIN_SECRET_LENGTH} characters)")
    if repository is None and settings.database_url is None:
        problems.append("database_url")
    if problems:
        raise ConfigurationError(f"missing or invalid settings: {', '.join(problems)}")

    if repository is None:
        repository = Repository(make_sessionmaker(engine_from_settings(settings)))
    open_clients: Clients = clients or (lambda: real_clients(settings))
    expected_secret = secret.encode()

    def verify_secret(x_webhook_secret: Annotated[str | None, Header()] = None) -> None:
        # Constant-time comparison, so response timing reveals nothing about the secret.
        supplied = (x_webhook_secret or "").encode()
        if not supplied or not hmac.compare_digest(supplied, expected_secret):
            raise HTTPException(status_code=401, detail="unauthorized")

    app = FastAPI(title="OrderBridge", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/ghl/deal-won", dependencies=[Depends(verify_secret)])
    def deal_won(event: DealWonEvent):
        # A plain `def` runs in a worker thread, which suits the synchronous clients and database.
        try:
            with open_clients() as (contacts, customers):
                result = handle_deal_won(event, repository, contacts, customers)
        except TEMPORARY_ERRORS as error:
            headers = {}
            retry_after = getattr(error, "retry_after", None)
            if retry_after is not None:
                headers["Retry-After"] = str(max(1, math.ceil(retry_after)))
            return JSONResponse(
                status_code=503, content={"detail": "temporarily unavailable"}, headers=headers
            )
        except Exception as error:  # noqa: BLE001 - the boundary: any failure becomes a generic 500
            # Log only the class name: messages and traces could contain customer data.
            logger.error("deal-won processing failed: %s", type(error).__name__)
            return JSONResponse(
                status_code=500, content={"detail": "processing failed; see the audit log"}
            )
        return {"status": result.status, "idempotency": result.idempotency}

    return app
