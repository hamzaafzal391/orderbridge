"""Business logic: tell the sales rep whether the ERP has the goods a deal asks for.

Framework-free like the other services. It reads the deal from the CRM, reads the stock from the
ERP and, when asked to apply, writes one short sentence back onto the deal. The ERP is only ever
read. The check is deliberately not guarded by an idempotency key: stock changes over time, so
each run should give a fresh answer, and repeating it is harmless (ADR 0009).

The sentence holds the SKU, quantities and warehouse names only, never customer data.
"""

from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.db.repository import Repository
from app.errors import UnknownItemError
from app.models import Deal, StockLevel


class DealCRM(Protocol):
    """Anything that can read a deal and write the availability note onto it."""

    def get_deal(self, opportunity_id: str) -> Deal: ...

    def set_availability_note(self, opportunity_id: str, note: str) -> None: ...


class StockSource(Protocol):
    """Anything that can say how much of an item each warehouse holds."""

    def get_stock(self, sku: str) -> list[StockLevel]:
        """Raise UnknownItemError if the item does not exist at all."""
        ...


class QuoteRequestedEvent(BaseModel):
    """The small message our GoHighLevel workflow sends. It carries only the deal's id: the
    SKU, quantity and warehouse are read from the CRM, never trusted from the message."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    opportunity_id: str = Field(min_length=1, max_length=200)


class AvailabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    # available:       the deal's warehouse can supply the quantity
    # short:           it cannot (the message names warehouses that can)
    # incomplete_deal: the deal lacks a SKU, quantity or warehouse; the message says which
    # unknown_item:    the ERP has no such item
    # wrong_pipeline:  the deal is not in the pipeline OrderBridge may act on; nothing is written
    status: Literal["available", "short", "incomplete_deal", "unknown_item", "wrong_pipeline"]
    message: str | None = None  # the sentence for the rep; None only for wrong_pipeline
    written: bool = False  # True only if the sentence was really written onto the deal


def quantity_text(value: Decimal) -> str:
    """4, not 4.0 or 4E+0."""
    return format(value.normalize(), "f")


def build_message(deal: Deal, levels: list[StockLevel]) -> tuple[str, bool]:
    """The sentence for the rep, and whether the deal's warehouse can supply the quantity.

    The deal must already be known to be complete.
    """
    assert deal.sku is not None and deal.quantity is not None and deal.warehouse is not None
    need = deal.quantity
    # A warehouse that holds none of the item has no row at all. Oversold stock counts as none.
    available = {level.warehouse: max(level.available, Decimal(0)) for level in levels}
    here = available.get(deal.warehouse, Decimal(0))

    if here >= need:
        return (
            f"OK: {quantity_text(here)} available in {deal.warehouse} (need {quantity_text(need)})",
            True,
        )

    message = (
        f"SHORT: {quantity_text(here)} available in {deal.warehouse} (need {quantity_text(need)})."
    )
    others = [
        f"{warehouse} has {quantity_text(count)} available"
        for warehouse, count in sorted(available.items())
        if warehouse != deal.warehouse and count >= need
    ]
    if others:
        return f"{message} {'; '.join(others)}.", False
    return f"{message} No other warehouse has enough.", False


def missing_parts(deal: Deal) -> list[str]:
    missing = []
    if not deal.sku:
        missing.append("SKU")
    if deal.quantity is None or deal.quantity <= 0:
        missing.append("quantity above zero")
    if not deal.warehouse:
        missing.append("warehouse")
    return missing


def check_availability(
    opportunity_id: str,
    crm: DealCRM,
    erp: StockSource,
    *,
    allowed_pipeline_id: str,
    apply: bool,
    audit: Repository | None = None,
) -> AvailabilityResult:
    """Work out the stock answer for one deal; write it onto the deal only when `apply` is true.

    Errors from the clients propagate after being noted in the audit log (class name only).
    """
    audit_key = f"availability:{opportunity_id}"

    def record(outcome: str) -> None:
        # Ids and statuses only: never names, emails, messages or error text.
        if audit is not None:
            audit.record_audit(
                audit_key,
                "availability",
                outcome,
                {"opportunity_id": opportunity_id, "apply": apply},
            )

    try:
        result = _check(opportunity_id, crm, erp, allowed_pipeline_id, apply)
    except Exception as error:
        record(type(error).__name__)
        raise
    record(result.status)
    return result


def _check(
    opportunity_id: str,
    crm: DealCRM,
    erp: StockSource,
    allowed_pipeline_id: str,
    apply: bool,
) -> AvailabilityResult:
    deal = crm.get_deal(opportunity_id)

    if deal.pipeline_id != allowed_pipeline_id:
        return AvailabilityResult(status="wrong_pipeline")

    missing = missing_parts(deal)
    status: Literal["available", "short", "incomplete_deal", "unknown_item"]
    if missing:
        status, message = "incomplete_deal", f"CANNOT CHECK: the deal needs {', '.join(missing)}."
    else:
        assert deal.sku is not None  # missing_parts() would have reported it
        try:
            levels = erp.get_stock(deal.sku)
        except UnknownItemError:
            status = "unknown_item"
            message = f"CANNOT CHECK: item {deal.sku} is not in the ERP."
        else:
            message, enough = build_message(deal, levels)
            status = "available" if enough else "short"

    if apply:
        crm.set_availability_note(opportunity_id, message)
    return AvailabilityResult(status=status, message=message, written=apply)
