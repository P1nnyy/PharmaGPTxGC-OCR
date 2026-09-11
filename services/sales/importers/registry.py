"""Choosing an adapter for a file, and remembering how its columns map.

Order matters. GSTR-1 JSON is tried first because it is the most specific — it
recognises a file by two named fields rather than by shape — and the tabular
adapter is last because "has commas and a header row" claims almost anything
that is not something else.

A file no adapter recognises is refused by name rather than guessed at. The
whole point of the sniff step is that an adapter which is not sure says so.
"""

from typing import Optional

from services.sales.importers.base import ImportAdapter, ImportRejected
from services.sales.importers.gstr1_json import Gstr1JsonAdapter
from services.sales.importers.tabular import TabularAdapter

# Most specific first. Marg and Vyapar adapters slot in above `TabularAdapter`
# once we have real exports to write their sniffers against; until then those
# formats import through the generic adapter with a mapping the user confirms,
# which works today and cannot silently mis-map a column the way a guessed
# sniffer could.
ADAPTERS: "list[ImportAdapter]" = [
    Gstr1JsonAdapter(),
    TabularAdapter(),
]


def adapter_by_name(name: str) -> Optional[ImportAdapter]:
    return next((a for a in ADAPTERS if a.name == name), None)


def detect(data: bytes, filename: Optional[str] = None) -> ImportAdapter:
    """The adapter that recognises this file, or a refusal naming the file.

    A sniff that raises is treated as "not mine" rather than propagating: one
    adapter throwing on a file meant for another must not stop the others being
    asked.
    """
    for adapter in ADAPTERS:
        try:
            if adapter.sniff(data, filename):
                return adapter
        except Exception:
            continue
    raise ImportRejected(
        f"Could not tell what kind of file {filename or 'this'} is. Supported: "
        + ", ".join(a.label for a in ADAPTERS)
        + "."
    )


def describe() -> "list[dict]":
    """The formats on offer, for a UI to list."""
    return [{"name": a.name, "label": a.label} for a in ADAPTERS]
