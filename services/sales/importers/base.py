"""The import adapter interface.

Shops export their day book from software we have never seen, in formats that
change between versions of that software. Two things follow.

First, the interface is deliberately tiny — `sniff` to recognise a file and
`parse` to read it — so adding a format is one small module and no changes
anywhere else.

Second, no adapter is trusted to be right about a tax figure just because it
parsed cleanly. Every adapter reconciles what it read against whatever totals
the file itself declares, and raises `ImportRejected` rather than importing a
file that contradicts itself. A silently mis-mapped amount column is precisely
the failure this whole layer exists to prevent, because it does not look like
a failure — it looks like a successful import of wrong numbers.
"""

from typing import Any, Optional, Protocol, runtime_checkable


class ImportRejected(ValueError):
    """Raised when a file cannot be imported. Message is user-facing."""


@runtime_checkable
class ImportAdapter(Protocol):
    """One file format.

    `name` and `label` identify the adapter to the UI and are what a remembered
    column mapping is filed under.
    """

    name: str
    label: str

    def sniff(self, data: bytes, filename: Optional[str] = None) -> bool:
        """True if this adapter recognises the file.

        Must be cheap and must never raise: it is called on every registered
        adapter in turn, on a file none of them may recognise.
        """
        ...

    def parse(self, data: bytes, filename: Optional[str] = None, **options: Any) -> "list[dict]":
        """Reads the file into sale drafts, or raises `ImportRejected`.

        Each draft carries the same keys the day-total path produces, so the
        repository stores every capture mode through one code path.
        """
        ...
