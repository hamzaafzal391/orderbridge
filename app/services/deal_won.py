"""Business logic: handle a "deal won" message exactly once.

Framework-free like the other services: the web layer (app/api.py) only authenticates and
translates. It claims an idempotency key for the deal, so a repeated or simultaneous message does
nothing, runs the customer engine, and records what happened.

For now the only work done for a won deal is making sure its customer exists in the ERP. Creating
the Sales Order comes in a later step.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.db.repository import ClaimResult, Repository
from app.services.customer_matching import ContactSource
from app.services.customer_sync import ERPCustomers, sync_contact

# Outcomes that need a person to fix the data. They are recorded as failed (not succeeded) so the
# same event can be replayed and reclaimed once the data is fixed.
NEEDS_REVIEW = {"no_email", "ambiguous", "name_conflict"}


class DealWonEvent(BaseModel):
    """The small message our GoHighLevel workflow sends. Other fields are ignored."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    opportunity_id: str = Field(min_length=1, max_length=200)
    contact_id: str = Field(min_length=1, max_length=200)


class DealWonResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    # "duplicate" and "in_progress" mean nothing was done; otherwise the customer engine's status
    # (already_matched, created, no_email, ambiguous, name_conflict).
    status: str
    idempotency: ClaimResult


def idempotency_key(opportunity_id: str) -> str:
    """One key per deal: the same deal always maps to the same key."""
    return f"ghl:opportunity-won:{opportunity_id}"


def handle_deal_won(
    event: DealWonEvent,
    repo: Repository,
    contacts: ContactSource,
    customers: ERPCustomers,
) -> DealWonResult:
    """Process a won deal at most once at a time. Vendor errors are recorded and re-raised."""
    key = idempotency_key(event.opportunity_id)
    claim = repo.claim(key)
    # Ids only: never emails, names or error messages.
    ids = {"opportunity_id": event.opportunity_id, "contact_id": event.contact_id}
    repo.record_audit(key, "webhook", claim, ids)

    if claim in ("duplicate", "in_progress"):
        return DealWonResult(status=claim, idempotency=claim)

    try:
        outcome = sync_contact(event.contact_id, contacts, customers, dry_run=False)
    except Exception as error:
        # Record the failure so the key can be replayed, then let the caller decide what to answer.
        error_class = type(error).__name__
        repo.mark_failed(key, error_class)
        repo.record_audit(key, "sync", error_class, ids)
        raise

    if outcome.status in NEEDS_REVIEW:
        repo.mark_failed(key, f"needs_review:{outcome.status}")
    else:
        repo.mark_succeeded(key, {"sync_status": outcome.status})
    repo.record_audit(key, "sync", outcome.status, ids)
    return DealWonResult(status=outcome.status, idempotency=claim)
