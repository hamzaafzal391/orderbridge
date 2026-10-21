"""Errors the business logic understands. They carry no vendor details.

Vendor clients raise their own errors (ERPNextNotFoundError, ...); where the business logic needs
to react to one, the client's error also inherits from one of these.
"""


class UnknownItemError(Exception):
    """The ERP has no such item. That is different from knowing the item and having none."""
