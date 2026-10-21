"""The availability service: what it says, what it writes, and what it refuses to do."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.clients.ghl_errors import GHLAuthenticationError, GHLTemporaryError
from app.db.models import Base
from app.db.repository import Repository
from app.db.session import make_engine, make_sessionmaker
from app.errors import UnknownItemError
from app.models import Deal, StockLevel
from app.services.availability import build_message, check_availability, quantity_text

PIPELINE = "pipe1"
DALLAS = "Dallas Warehouse - MAS"
HOUSTON = "Houston Warehouse - MAS"


def level(warehouse: str, on_hand: int, reserved: int = 0) -> StockLevel:
    return StockLevel(warehouse=warehouse, on_hand=Decimal(on_hand), reserved=Decimal(reserved))


def make_deal(**overrides: object) -> Deal:
    values: dict = {
        "id": "opp1",
        "contact_id": "contact1",
        "status": "open",
        "pipeline_id": PIPELINE,
        "sku": "AC-5TON-RTU",
        "quantity": Decimal(4),
        "warehouse": DALLAS,
        "unit_price": Decimal(4200),
    }
    values.update(overrides)
    return Deal(**values)


class FakeCRM:
    def __init__(self, deal: Deal | None = None, error: Exception | None = None) -> None:
        self.deal = deal or make_deal()
        self.error = error
        self.write_error: Exception | None = None
        self.written: list[tuple[str, str]] = []

    def get_deal(self, opportunity_id: str) -> Deal:
        if self.error:
            raise self.error
        return self.deal

    def set_availability_note(self, opportunity_id: str, note: str) -> None:
        if self.write_error:
            raise self.write_error
        self.written.append((opportunity_id, note))


class FakeERP:
    def __init__(self, levels: list[StockLevel] | None = None) -> None:
        self.levels = [level(DALLAS, 7, 1), level(HOUSTON, 7)] if levels is None else levels
        self.error: Exception | None = None
        self.asked: list[str] = []

    def get_stock(self, sku: str) -> list[StockLevel]:
        self.asked.append(sku)
        if self.error:
            raise self.error
        return self.levels


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    engine = make_engine(f"sqlite:///{tmp_path / 'availability.db'}")
    Base.metadata.create_all(engine)
    return Repository(make_sessionmaker(engine), stale_after=timedelta(minutes=10))


def run(crm: FakeCRM, erp: FakeERP, *, apply: bool = False, audit: Repository | None = None):
    return check_availability(
        "opp1", crm, erp, allowed_pipeline_id=PIPELINE, apply=apply, audit=audit
    )


# --- the sentence ---------------------------------------------------------------------------


def test_enough_stock_in_the_deals_warehouse() -> None:
    result = run(FakeCRM(), FakeERP())  # Dallas: 7 on hand, 1 reserved, 6 available
    assert result.status == "available"
    assert result.message == "OK: 6 available in Dallas Warehouse - MAS (need 4)"


def test_exactly_enough_is_enough() -> None:
    erp = FakeERP([level(DALLAS, 4)])
    assert run(FakeCRM(), erp).status == "available"


def test_short_stock_names_the_warehouse_that_can_cover_it() -> None:
    erp = FakeERP([level(DALLAS, 3, 1), level(HOUSTON, 7)])
    result = run(FakeCRM(), erp)
    assert result.status == "short"
    assert result.message == (
        "SHORT: 2 available in Dallas Warehouse - MAS (need 4). "
        "Houston Warehouse - MAS has 7 available."
    )


def test_a_warehouse_with_too_little_is_not_offered_as_an_alternative() -> None:
    erp = FakeERP([level(DALLAS, 1), level(HOUSTON, 3)])
    result = run(FakeCRM(), erp)
    assert result.message == (
        "SHORT: 1 available in Dallas Warehouse - MAS (need 4). No other warehouse has enough."
    )


def test_a_warehouse_that_holds_none_of_the_item_counts_as_zero() -> None:
    erp = FakeERP([level(HOUSTON, 7)])
    result = run(FakeCRM(), erp)
    assert result.status == "short"
    assert result.message.startswith("SHORT: 0 available in Dallas Warehouse - MAS (need 4).")
    assert "Houston Warehouse - MAS has 7 available." in result.message


def test_oversold_stock_is_reported_as_zero_not_negative() -> None:
    erp = FakeERP([level(DALLAS, 2, 5)])
    assert run(FakeCRM(), erp).message.startswith("SHORT: 0 available")


def test_several_alternatives_are_all_listed_in_order() -> None:
    erp = FakeERP([level(DALLAS, 0), level("Z Depot", 9), level(HOUSTON, 5)])
    message = run(FakeCRM(), erp).message
    assert message.endswith("Houston Warehouse - MAS has 5 available; Z Depot has 9 available.")


@pytest.mark.parametrize(
    ("value", "text"),
    [("4", "4"), ("4.0", "4"), ("0E+1", "0"), ("2.50", "2.5"), ("100", "100")],
)
def test_quantities_are_written_without_noise(value: str, text: str) -> None:
    assert quantity_text(Decimal(value)) == text


def test_the_sentence_holds_no_customer_data() -> None:
    deal = make_deal(contact_id="Jordan Lee jordan.lee@northstar.example.test")
    message, _ = build_message(deal, [level(DALLAS, 7)])
    assert "Jordan" not in message and "@" not in message


# --- incomplete or unknown -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "needs"),
    [
        ({"sku": None}, "SKU"),
        ({"quantity": None}, "quantity above zero"),
        ({"quantity": Decimal(0)}, "quantity above zero"),
        ({"quantity": Decimal(-2)}, "quantity above zero"),
        ({"warehouse": None}, "warehouse"),
        ({"sku": None, "warehouse": None}, "SKU, warehouse"),
    ],
)
def test_an_incomplete_deal_says_what_is_missing_and_never_asks_the_erp(
    overrides: dict, needs: str
) -> None:
    erp = FakeERP()
    result = run(FakeCRM(make_deal(**overrides)), erp)
    assert result.status == "incomplete_deal"
    assert result.message == f"CANNOT CHECK: the deal needs {needs}."
    assert erp.asked == []


def test_an_unknown_item_is_reported_not_called_out_of_stock() -> None:
    erp = FakeERP()
    erp.error = UnknownItemError()
    result = run(FakeCRM(make_deal(sku="NOPE")), erp)
    assert result.status == "unknown_item"
    assert result.message == "CANNOT CHECK: item NOPE is not in the ERP."


# --- the fence --------------------------------------------------------------------------------


def test_a_deal_in_another_pipeline_is_ignored_completely() -> None:
    crm, erp = FakeCRM(make_deal(pipeline_id="someone-elses-pipeline")), FakeERP()
    result = run(crm, erp, apply=True)

    assert result.status == "wrong_pipeline"
    assert result.message is None
    assert result.written is False
    assert erp.asked == []  # the ERP is not even asked
    assert crm.written == []  # and nothing is written, even with apply


# --- writing ----------------------------------------------------------------------------------


def test_a_dry_run_writes_nothing() -> None:
    crm = FakeCRM()
    result = run(crm, FakeERP(), apply=False)
    assert result.written is False
    assert result.message is not None
    assert crm.written == []


def test_apply_writes_the_sentence_onto_the_deal() -> None:
    crm = FakeCRM()
    result = run(crm, FakeERP(), apply=True)
    assert result.written is True
    assert crm.written == [("opp1", "OK: 6 available in Dallas Warehouse - MAS (need 4)")]


@pytest.mark.parametrize(
    "deal",
    [make_deal(sku=None), make_deal(sku="NOPE")],
    ids=["incomplete", "unknown item"],
)
def test_apply_also_tells_the_rep_when_it_cannot_check(deal: Deal) -> None:
    erp = FakeERP()
    erp.error = UnknownItemError()
    crm = FakeCRM(deal)
    run(crm, erp, apply=True)
    assert len(crm.written) == 1
    assert crm.written[0][1].startswith("CANNOT CHECK")


def test_checking_twice_asks_the_erp_twice_and_gives_a_fresh_answer() -> None:
    crm, erp = FakeCRM(), FakeERP()
    first = run(crm, erp, apply=True)
    erp.levels = [level(DALLAS, 2)]  # stock changed in between
    second = run(crm, erp, apply=True)

    assert first.status == "available" and second.status == "short"
    assert erp.asked == ["AC-5TON-RTU", "AC-5TON-RTU"]
    assert len(crm.written) == 2


# --- failures ---------------------------------------------------------------------------------


def test_a_crm_failure_propagates() -> None:
    with pytest.raises(GHLTemporaryError):
        run(FakeCRM(error=GHLTemporaryError("down")), FakeERP())


def test_a_failed_write_propagates() -> None:
    crm = FakeCRM()
    crm.write_error = GHLAuthenticationError("no permission", status_code=403)
    with pytest.raises(GHLAuthenticationError):
        run(crm, FakeERP(), apply=True)


# --- audit ------------------------------------------------------------------------------------


def test_each_check_is_audited_with_ids_and_the_result_only(repo: Repository) -> None:
    run(FakeCRM(), FakeERP(), apply=True, audit=repo)
    run(FakeCRM(), FakeERP(), apply=False, audit=repo)

    entries = repo.list_audit("availability:opp1")
    assert [(e.action, e.outcome) for e in entries] == [
        ("availability", "available"),
        ("availability", "available"),
    ]
    assert entries[0].detail == {"opportunity_id": "opp1", "apply": True}
    assert entries[1].detail == {"opportunity_id": "opp1", "apply": False}


def test_a_failure_is_audited_by_class_name_only(repo: Repository) -> None:
    crm = FakeCRM(error=GHLTemporaryError("secret customer details"))
    with pytest.raises(GHLTemporaryError):
        run(crm, FakeERP(), audit=repo)

    (entry,) = repo.list_audit("availability:opp1")
    assert entry.outcome == "GHLTemporaryError"
    assert "secret" not in str(entry)


def test_repeated_checks_are_never_blocked_by_an_idempotency_key(repo: Repository) -> None:
    for _ in range(3):
        run(FakeCRM(), FakeERP(), audit=repo)
    assert repo.status_of("availability:opp1") is None
    assert len(repo.list_audit("availability:opp1")) == 3
