import io

import pytest
from pydantic import ValidationError

from app import cli
from app.api import ConfigurationError
from app.clients.erpnext_errors import (
    ERPNextDuplicateCreatedError,
    ERPNextPartialWriteError,
    ERPNextTemporaryError,
)
from app.clients.ghl_errors import GHLNotFoundError
from app.config import Settings
from app.models import Customer

DRY_RUN_HEADER = "mode: dry run (nothing will be written; use --apply to write)"
APPLY_HEADER = "mode: APPLY (will write to ERPNext if needed)"


class FakeContacts:
    def __init__(self, customer: Customer | None = None, error: Exception | None = None) -> None:
        self.customer = customer or crm()
        self.error = error
        self.closed = False

    def get_contact(self, contact_id: str) -> Customer:
        if self.error:
            raise self.error
        return self.customer

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True


class FakeERP:
    def __init__(
        self,
        existing: list[Customer] | None = None,
        create_result: Customer | None = None,
        create_error: Exception | None = None,
    ) -> None:
        self.existing = existing or []
        self.create_result = create_result
        self.create_error = create_error
        self.created_from: list[Customer] = []
        self.closed = False

    def find_customers_by_email(self, email: str) -> list[Customer]:
        return self.existing

    def create_customer(self, customer: Customer) -> Customer | None:
        self.created_from.append(customer)
        if self.create_error:
            raise self.create_error
        return self.create_result

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True


def crm(email: str | None = "sam@example.com") -> Customer:
    return Customer(name="Sam Rivera", customer_type="Individual", email=email)


def erp_customer(name: str) -> Customer:
    return Customer(name=name, customer_type="Company", email="sam@example.com")


def run(argv: list[str], contacts: FakeContacts, erp: FakeERP) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, contacts=contacts, erp=erp, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# --- results, exit codes and the dry-run default -------------------------------------------


def test_default_is_a_dry_run_and_never_writes() -> None:
    erp = FakeERP(create_result=erp_customer("Sam Rivera"))

    code, out, _ = run(["sync", "c1"], FakeContacts(), erp)

    assert code == 0
    assert out.splitlines() == [
        DRY_RUN_HEADER,
        'would_create: no ERPNext customer yet; --apply would create "Sam Rivera"',
    ]
    assert erp.created_from == []


def test_apply_creates_exactly_once() -> None:
    erp = FakeERP(create_result=erp_customer("Sam Rivera"))

    code, out, _ = run(["sync", "c1", "--apply"], FakeContacts(), erp)

    assert code == 0
    assert out.splitlines() == [
        APPLY_HEADER,
        'created: ERPNext customer "Sam Rivera" created, with a contact holding the email',
    ]
    assert len(erp.created_from) == 1


@pytest.mark.parametrize("apply_flag", [[], ["--apply"]])
def test_already_matched_writes_nothing_even_with_apply(apply_flag: list[str]) -> None:
    erp = FakeERP(existing=[erp_customer("Acme")], create_result=erp_customer("x"))

    code, out, _ = run(["sync", "c1", *apply_flag], FakeContacts(), erp)

    assert code == 0
    assert out.splitlines()[-1] == 'already_matched: matches ERPNext customer "Acme"'
    assert erp.created_from == []


def test_no_email_needs_a_person() -> None:
    code, out, _ = run(["sync", "c1", "--apply"], FakeContacts(crm(None)), FakeERP())

    assert code == 1
    assert out.splitlines()[-1] == "no_email: the contact has no email, so it cannot be matched"


def test_ambiguous_needs_a_person_and_writes_nothing() -> None:
    erp = FakeERP(existing=[erp_customer("Acme"), erp_customer("Acme 2")])

    code, out, _ = run(["sync", "c1", "--apply"], FakeContacts(), erp)

    assert code == 1
    assert out.splitlines()[-1] == (
        'ambiguous: 2 ERPNext customers share the email ("Acme", "Acme 2"); a person must decide'
    )
    assert erp.created_from == []


def test_name_conflict_needs_a_person() -> None:
    erp = FakeERP(create_result=None)  # create_customer reports "name already taken"

    code, out, _ = run(["sync", "c1", "--apply"], FakeContacts(), erp)

    assert code == 1
    assert out.splitlines()[-1] == (
        'name_conflict: an ERPNext customer named "Sam Rivera" already exists but is '
        "not linked to this email; nothing was changed"
    )


@pytest.mark.parametrize(
    ("argv", "erp"),
    [
        (["sync", "c1"], FakeERP(existing=[erp_customer("Acme")])),
        (["sync", "c1"], FakeERP(create_result=erp_customer("Sam Rivera"))),
        (["sync", "c1", "--apply"], FakeERP(create_result=erp_customer("Sam Rivera"))),
        (["sync", "c1", "--apply"], FakeERP(create_result=None)),
        (["sync", "c1"], FakeERP(existing=[erp_customer("Acme"), erp_customer("Acme 2")])),
    ],
    ids=["matched", "would_create", "created", "name_conflict", "ambiguous"],
)
def test_emails_are_never_printed(argv: list[str], erp: FakeERP) -> None:
    _, out, err = run(argv, FakeContacts(), erp)

    assert "sam@example.com" not in out + err


# --- usage errors --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [[], ["sync"], ["sync", "c1", "--nope"], ["unknown", "c1"]],
    ids=["no-command", "no-contact-id", "unknown-flag", "unknown-command"],
)
def test_bad_usage_exits_with_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(argv) == 2
    assert "usage:" in capsys.readouterr().err


def test_help_exits_with_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["sync", "--help"]) == 0
    assert "--apply" in capsys.readouterr().out


# --- errors --------------------------------------------------------------------------------


def test_a_crm_error_exits_with_3_and_names_the_error() -> None:
    contacts = FakeContacts(error=GHLNotFoundError("contact not found"))

    code, out, err = run(["sync", "c1"], contacts, FakeERP())

    assert code == 3
    assert err.splitlines() == ["error: GHLNotFoundError: contact not found"]
    assert out.splitlines() == [DRY_RUN_HEADER]  # no result line


def test_a_temporary_erp_error_has_no_extra_hint() -> None:
    erp = FakeERP(create_error=ERPNextTemporaryError("down"))

    code, _, err = run(["sync", "c1", "--apply"], FakeContacts(), erp)

    assert code == 3
    assert err.splitlines() == ["error: ERPNextTemporaryError: down"]


@pytest.mark.parametrize(
    "error",
    [ERPNextPartialWriteError("half done"), ERPNextDuplicateCreatedError("numbered")],
    ids=["partial-write", "duplicate-created"],
)
def test_writes_that_need_checking_print_a_hint(error: Exception) -> None:
    erp = FakeERP(create_error=error)

    code, _, err = run(["sync", "c1", "--apply"], FakeContacts(), erp)

    assert code == 3
    assert err.splitlines()[0].startswith(f"error: {type(error).__name__}")
    assert "a person must check ERPNext before running this again" in err


def test_missing_settings_print_field_names_but_never_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("ERPNEXT_API_KEY", "ERPNEXT_API_SECRET", "GHL_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ERPNEXT_BASE_URL", "not a url SENSITIVE-VALUE")
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    def broken_client() -> None:
        raise info.value

    monkeypatch.setattr(cli, "GHLClient", broken_client)
    out, err = io.StringIO(), io.StringIO()

    code = cli.main(["sync", "c1"], out=out, err=err)

    assert code == 3
    assert err.getvalue().startswith("configuration error: missing or invalid settings: ")
    assert "erpnext_base_url" in err.getvalue()
    assert "SENSITIVE-VALUE" not in err.getvalue()


# --- real clients are built and always closed ----------------------------------------------


def test_real_clients_are_built_and_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    contacts = FakeContacts()
    erp = FakeERP(existing=[erp_customer("Acme")])
    monkeypatch.setattr(cli, "GHLClient", lambda: contacts)
    monkeypatch.setattr(cli, "ERPNextClient", lambda: erp)

    code = cli.main(["sync", "c1"], out=io.StringIO(), err=io.StringIO())

    assert code == 0
    assert contacts.closed
    assert erp.closed


def test_clients_are_closed_even_when_the_sync_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    contacts = FakeContacts(error=GHLNotFoundError("nope"))
    erp = FakeERP()
    monkeypatch.setattr(cli, "GHLClient", lambda: contacts)
    monkeypatch.setattr(cli, "ERPNextClient", lambda: erp)

    code = cli.main(["sync", "c1"], out=io.StringIO(), err=io.StringIO())

    assert code == 3
    assert contacts.closed
    assert erp.closed


# --- the serve command ---------------------------------------------------------------------


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, str, int]]:
    """Replace the real app and the real server, recording what would have been started."""
    calls: list[tuple[object, str, int]] = []
    sentinel = object()
    monkeypatch.setattr(cli, "create_app", lambda: sentinel)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, host, port: calls.append((app, host, port)))
    return calls


def test_serve_listens_locally_on_port_8000_by_default(served: list) -> None:
    out, err = io.StringIO(), io.StringIO()

    code = cli.main(["serve"], out=out, err=err)

    assert code == 0
    assert [(host, port) for _, host, port in served] == [("127.0.0.1", 8000)]
    assert out.getvalue() == ""  # no "mode: dry run" header: that belongs to `sync`


def test_serve_accepts_a_host_and_port(served: list) -> None:
    code = cli.main(["serve", "--host", "0.0.0.0", "--port", "9100"], out=io.StringIO())

    assert code == 0
    assert [(host, port) for _, host, port in served] == [("0.0.0.0", 9100)]


def test_serve_reports_missing_settings_and_does_not_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[object] = []

    def refuse() -> None:
        raise ConfigurationError(
            "missing or invalid settings: webhook_secret (at least 16 characters)"
        )

    monkeypatch.setattr(cli, "create_app", refuse)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: started.append(args))
    err = io.StringIO()

    code = cli.main(["serve"], out=io.StringIO(), err=err)

    assert code == 3
    assert err.getvalue().splitlines() == [
        "configuration error: missing or invalid settings: webhook_secret (at least 16 characters)"
    ]
    assert started == []


def test_serve_prints_field_names_but_never_values_for_invalid_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("ERPNEXT_API_KEY", "ERPNEXT_API_SECRET", "GHL_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ERPNEXT_BASE_URL", "not a url SENSITIVE-VALUE")
    with pytest.raises(ValidationError) as info:
        Settings(_env_file=None)  # type: ignore[call-arg]

    def broken() -> None:
        raise info.value

    monkeypatch.setattr(cli, "create_app", broken)
    err = io.StringIO()

    code = cli.main(["serve"], out=io.StringIO(), err=err)

    assert code == 3
    assert "erpnext_base_url" in err.getvalue()
    assert "SENSITIVE-VALUE" not in err.getvalue()


def test_serve_rejects_a_port_that_is_not_a_number(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["serve", "--port", "abc"]) == 2
    assert "usage:" in capsys.readouterr().err
