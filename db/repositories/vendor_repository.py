"""Distributors, and the one thing about them nobody was recording.

A pharmacy's expiry losses are not decided by when stock expires. They are
decided by whether it goes back to the distributor before the distributor stops
accepting it. Most wholesalers take saleable returns up to some number of
months before expiry - commonly three to six - and after that window the stock
is a write-off and its input credit has to be reversed permanently under
Section 17(5)(h).

That window is the difference between recovering the cost and losing it, and
nothing in this system knew it. It is per-vendor, it is not on any invoice, and
it is not derivable from anything we hold - so it is asked for, stored nullable,
and reported as unknown until somebody fills it in. A guessed window would be
worse than none: it would tell a shopkeeper they still had time when they did
not.
"""

from typing import Optional

from core.tenancy import current_tenant
from db.graph_db import get_driver


class VendorError(ValueError):
    """Raised when a vendor detail cannot be accepted."""


def _run_read(query: str, **params) -> list:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def _run_write(query: str, **params) -> list:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(lambda tx: [r.data() for r in tx.run(query, **params)])


def list_vendors(pharmacy_id: Optional[str] = None) -> list:
    """Every distributor this shop has bought from, with its return window."""
    pharmacy_id = pharmacy_id or current_tenant()
    return _run_read(
        """
        MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pid})
        MATCH (inv)-[:SUPPLIED_BY]->(v:Vendor)
        RETURN v.id AS vendor_id,
               v.name AS name,
               v.gstin AS gstin,
               v.return_window_days AS return_window_days,
               v.return_window_note AS return_window_note,
               count(inv) AS invoice_count,
               max(inv.invoice_date) AS last_invoice_date
        ORDER BY toLower(coalesce(v.name, ''))
        """,
        pid=pharmacy_id,
    )


def return_windows(pharmacy_id: Optional[str] = None) -> dict:
    """`vendor_id -> days`, for the reports that need to know.

    Vendors with no window recorded are absent rather than present with a
    default. The expiry report distinguishes "you have 40 days to send this
    back" from "nobody has told us this distributor's window", and a default
    would collapse the two into a claim we cannot support.
    """
    return {
        row["vendor_id"]: row["return_window_days"]
        for row in list_vendors(pharmacy_id)
        if row.get("return_window_days") is not None
    }


def set_return_window(
    vendor_id: str,
    days: Optional[int],
    note: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
) -> dict:
    """Records how long before expiry this distributor still takes stock back.

    `None` clears it, which is a real answer: a shop that learns its supplier
    has stopped accepting returns needs to be able to say so, and leaving a
    stale number would keep promising a route that has closed.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    if days is not None:
        if isinstance(days, bool) or not isinstance(days, int):
            raise VendorError("A return window is a whole number of days.")
        if days < 0 or days > 730:
            raise VendorError(
                "A return window is between 0 and 730 days. Anything longer is "
                "almost certainly a typo."
            )

    rows = _run_write(
        """
        MATCH (v:Vendor {id: $vendor_id})
        WHERE EXISTS {
            MATCH (inv:Invoice)-[:BELONGS_TO]->(:Pharmacy {id: $pid})
            WHERE (inv)-[:SUPPLIED_BY]->(v)
        }
        SET v.return_window_days = $days, v.return_window_note = $note
        RETURN v.id AS vendor_id, v.name AS name,
               v.return_window_days AS return_window_days,
               v.return_window_note AS return_window_note
        """,
        vendor_id=vendor_id, pid=pharmacy_id, days=days, note=note,
    )
    if not rows:
        # Scoped to vendors this shop actually buys from, so one workspace
        # cannot edit a distributor it has never dealt with.
        raise VendorError("That distributor is not one this shop has bought from.")
    return rows[0]
