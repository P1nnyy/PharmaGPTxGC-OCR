"""What changed on an invoice, in words a person can check.

The audit trail's job is to let someone ask "who changed the tax, and from
what?" months later. That needs the before value as well as the after, and it
needs field names a pharmacist recognises rather than column names.

Only the header is diffed field by field. Line items are replaced wholesale by
the review screen, so a per-cell diff of them would mostly be noise; they are
summarised as a count change instead, which is the part a reviewer would
actually query.
"""

from typing import Any, Optional

# Only fields worth recording a change to. A field absent here is either
# derived, or not something a reviewer edits.
TRACKED_FIELDS: dict[str, str] = {
    "invoice_number": "Invoice number",
    "invoice_date": "Invoice date",
    "seller_name": "Seller",
    "seller_gstin": "Seller GSTIN",
    "seller_address": "Seller address",
    "seller_phone": "Seller phone",
    "drug_license": "Drug licence",
    "buyer_gstin": "Buyer GSTIN",
    "subtotal": "Subtotal",
    "discount": "Discount",
    "cgst": "CGST",
    "sgst": "SGST",
    "igst": "IGST",
    "roundoff": "Round off",
    "grand_total": "Grand total",
}

# Money differences below this are float noise, not edits.
_EPSILON = 0.005


def _as_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _same(before: Any, after: Any) -> bool:
    """Whether two stored values are the same to a reviewer.

    Compares numerically when both sides look like numbers, so "89.08" typed
    into a box does not read as a change from the 89.08 already stored - the
    review screen resends every field on every save, and a naive comparison
    would record a dozen edits nobody made.
    """
    a, b = _as_number(before), _as_number(after)
    if a is not None and b is not None:
        return abs(a - b) < _EPSILON
    if (before is None or str(before).strip() == "") and (after is None or str(after).strip() == ""):
        return True
    return str(before).strip() == str(after).strip()


def _render(value: Any) -> str:
    """How a value reads in the log. Absence is named, not left blank."""
    if value is None or str(value).strip() == "":
        return "empty"
    number = _as_number(value)
    if number is not None:
        return f"{number:.2f}"
    return str(value).strip()


def header_changes(before: dict, after: dict) -> list[dict]:
    """One entry per field the caller actually changed.

    `after` holds only the fields the request sent, so a field the request
    omitted is untouched rather than cleared - the diff must not report an
    edit that the update itself will not make.
    """
    changes = []
    for field, label in TRACKED_FIELDS.items():
        if field not in after:
            continue
        old_value = before.get(field)
        new_value = after.get(field)
        if _same(old_value, new_value):
            continue
        changes.append({
            "field": field,
            "label": label,
            "from": _render(old_value),
            "to": _render(new_value),
        })
    return changes


def line_item_change(before_count: int, after_count: Optional[int]) -> Optional[dict]:
    """A summary of the rows, when the count moved.

    Deliberately not a per-cell diff: the review screen resends the whole
    table on every save, so cell-level comparison would report the entire
    invoice as edited whenever one row moved.
    """
    if after_count is None or after_count == before_count:
        return None
    return {
        "field": "line_items",
        "label": "Line items",
        "from": str(before_count),
        "to": str(after_count),
    }


def summarise(actor_name: str, changes: list[dict]) -> str:
    """A one-line description for the activity feed."""
    if not changes:
        return f"{actor_name} saved the invoice with no changes"
    labels = [c["label"] for c in changes]
    if len(labels) == 1:
        only = changes[0]
        return f"{actor_name} changed {only['label']} from {only['from']} to {only['to']}"
    if len(labels) <= 3:
        return f"{actor_name} changed {', '.join(labels[:-1])} and {labels[-1]}"
    return f"{actor_name} changed {len(labels)} fields including {', '.join(labels[:2])}"


def as_details(changes: list[dict]) -> list[str]:
    """Flattened for storage - Neo4j cannot hold a list of maps on a node."""
    return [f"{c['label']}: {c['from']} -> {c['to']}" for c in changes]
