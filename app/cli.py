"""Command line: `python -m app sync <contact_id> [--apply]`.

A thin layer over `sync_contact`: it parses arguments, builds the real clients, prints a short
plain-English result and returns an exit code. All decisions live in the service.

Dry run is the default. Nothing is written to ERPNext unless `--apply` is given.
Output goes to the operator's terminal. It may name customers (so the operator can act) but
never prints emails, tokens, response bodies or credentials.
"""

import argparse
import sys
from contextlib import ExitStack
from typing import TextIO

from pydantic import ValidationError

from app.clients.erpnext import ERPNextClient
from app.clients.erpnext_errors import (
    ERPNextDuplicateCreatedError,
    ERPNextError,
    ERPNextPartialWriteError,
)
from app.clients.ghl import GHLClient
from app.clients.ghl_errors import GHLError
from app.services.customer_matching import ContactSource
from app.services.customer_sync import ERPCustomers, SyncResult, sync_contact

EXIT_OK = 0  # matched, created or would_create
EXIT_NEEDS_PERSON = 1  # no_email, ambiguous or name_conflict: a person must look
# Exit code 2 is argparse's own "bad usage".
EXIT_ERROR = 3  # configuration problem or a service error

OK_STATUSES = {"already_matched", "created", "would_create"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="Keep ERPNext customers in step with CRM contacts.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    sync = commands.add_parser(
        "sync",
        help="match a CRM contact to an ERPNext customer, creating it if missing",
        description="Match a GoHighLevel contact to an ERPNext customer by email. "
        "By default this is a dry run: nothing is written.",
    )
    sync.add_argument("contact_id", help="the GoHighLevel contact ID")
    sync.add_argument(
        "--apply",
        action="store_true",
        help="really create the missing ERPNext customer (default: dry run, no writes)",
    )
    return parser


def describe(result: SyncResult) -> str:
    """One plain-English line for a result. Names only; never emails."""
    crm_name = result.crm_customer.name
    erp_names = ", ".join(f'"{customer.name}"' for customer in result.erp_customers)

    match result.status:
        case "already_matched":
            return f"already_matched: matches ERPNext customer {erp_names}"
        case "would_create":
            return f'would_create: no ERPNext customer yet; --apply would create "{crm_name}"'
        case "created":
            return (
                f"created: ERPNext customer {erp_names} created, with a contact holding the email"
            )
        case "no_email":
            return "no_email: the contact has no email, so it cannot be matched"
        case "ambiguous":
            count = len(result.erp_customers)
            return (
                f"ambiguous: {count} ERPNext customers share the email ({erp_names}); "
                "a person must decide"
            )
        case "name_conflict":
            return (
                f'name_conflict: an ERPNext customer named "{crm_name}" already exists but is '
                "not linked to this email; nothing was changed"
            )
    raise ValueError(f"unknown status: {result.status}")  # pragma: no cover


def main(
    argv: list[str] | None = None,
    *,
    contacts: ContactSource | None = None,
    erp: ERPCustomers | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run the CLI and return the exit code. `contacts` and `erp` are injected by tests."""
    out = out or sys.stdout
    err = err or sys.stderr

    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exit_:  # argparse exits on bad usage and on --help
        return int(exit_.code or 0)

    dry_run = not args.apply
    if dry_run:
        print("mode: dry run (nothing will be written; use --apply to write)", file=out)
    else:
        print("mode: APPLY (will write to ERPNext if needed)", file=out)

    with ExitStack() as stack:
        try:
            if contacts is None:
                contacts = stack.enter_context(GHLClient())
            if erp is None:
                erp = stack.enter_context(ERPNextClient())
        except ValidationError as error:
            fields = sorted({str(item["loc"][0]) for item in error.errors() if item["loc"]})
            print(
                f"configuration error: missing or invalid settings: {', '.join(fields)}",
                file=err,
            )
            return EXIT_ERROR

        try:
            result = sync_contact(args.contact_id, contacts, erp, dry_run=dry_run)
        except (GHLError, ERPNextError) as error:
            print(f"error: {type(error).__name__}: {error}", file=err)
            if isinstance(error, ERPNextPartialWriteError | ERPNextDuplicateCreatedError):
                print("a person must check ERPNext before running this again", file=err)
            return EXIT_ERROR

    print(describe(result), file=out)
    return EXIT_OK if result.status in OK_STATUSES else EXIT_NEEDS_PERSON
