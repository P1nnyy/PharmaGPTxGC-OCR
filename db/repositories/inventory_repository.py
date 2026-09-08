"""Stock on hand, derived from verified invoices.

Inventory is not a stored table. It is a reading of the purchase history:
every verified line item is stock that came in, and the same product/batch
bought twice is one holding of two deliveries, not two rows. Deriving it on
read rather than maintaining a parallel table means it cannot drift from the
invoices it came from - correcting a quantity on the review screen corrects
the stock figure, with nothing to re-sync.

The obvious caveat: with no sales or dispensing feed, these are quantities
received, not quantities remaining. Every field here is honest about that -
`quantity` is what was purchased. When a dispensing source exists, it
subtracts here and the rest of the shape holds.
"""

from datetime import date, timedelta
from typing import Any, Optional

from db.graph_db import get_driver

# Verified-only by default, for the same reason the reports are: an invoice
# still in review may have an OCR error in the very quantity being totalled.
DEFAULT_STATUSES = ["verified"]

# A pharmacy counts "nearly out" in packs, not in a percentage of some
# reorder level we do not have. Ten is the figure the page has always used;
# it lives here now so it is one number rather than one per caller.
LOW_STOCK_THRESHOLD = 10.0

# Six months. Pharma wholesalers will not take back stock inside this window,
# so it is the point at which a batch stops being an asset and starts being a
# decision.
EXPIRING_WITHIN_DAYS = 180

# One row per product/batch holding. Grouping on the catalogue product rather
# than the printed name is what merges "MONTICOPE SUSP" and "MONTICOPE
# SUSPENSION 60 ML" into a single holding; lines that never resolved to a
# product fall back to their own spelling and stay separate, which is the
# honest reading - we do not know they are the same thing.
_STOCK_QUERY = """
    MATCH (inv:Invoice)-[:CONTAINS]->(li:LineItem)
    WHERE ($statuses IS NULL OR inv.status IN $statuses)
    OPTIONAL MATCH (li)-[:OF_PRODUCT]->(p:Product)
    OPTIONAL MATCH (li)-[:OF_ALIAS]->(al:ProductAlias)
    OPTIONAL MATCH (li)-[:OF_BATCH]->(b:Batch)

    WITH
        li, inv, p,
        coalesce(p.id, 'unmatched:' + toLower(trim(coalesce(al.raw_name, '?')))) AS group_key,
        coalesce(p.canonical_name, al.raw_name)                                  AS product_name,
        coalesce(b.batch_number, li.batch)                                       AS batch_number,
        coalesce(b.expiry_date, li.expiry)                                       AS expiry_date
    WHERE product_name IS NOT NULL AND trim(product_name) <> ''

    // Newest delivery first, so head() below reads "as most recently billed"
    // for the figures that are a current fact rather than a running total.
    ORDER BY coalesce(inv.invoice_date, '') DESC

    WITH
        group_key, batch_number,
        head(collect(product_name))                                    AS product,
        head(collect(p.id))                                            AS product_id,
        head(collect(expiry_date))                                     AS expiry,
        // MRP and GST are the pack's current price and tax rate, not
        // something to add up across deliveries - the latest bill wins.
        head(collect(li.mrp))                                          AS mrp,
        head(collect(li.gst_percent))                                  AS gst,
        head(collect(inv.invoice_number))                              AS latest_invoice,
        // Free goods are stock on the shelf even though they were not
        // charged for, so they count toward what is held.
        sum(coalesce(li.quantity, 0.0) + coalesce(li.free_quantity, 0.0)) AS quantity,
        sum(coalesce(li.free_quantity, 0.0))                           AS free_quantity,
        count(DISTINCT inv.id)                                         AS deliveries

    RETURN
        group_key, batch_number, product, product_id, expiry,
        mrp, gst, latest_invoice, quantity, free_quantity, deliveries
    ORDER BY toLower(product), batch_number
"""


def _run(query: str, **params) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def _parse_expiry(value: Optional[str]) -> Optional[date]:
    """Reads a stored expiry, tolerating the shapes that predate normalising.

    Expiries are written as ISO by `core.dates.normalize_expiry`, but rows
    saved before that landed can still hold `MM/YY`. An unreadable expiry
    returns None and is treated as "not known to be expiring" rather than
    being defaulted into either answer.
    """
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    parts = text.replace("-", "/").split("/")
    if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
        month, year = int(parts[0]), int(parts[1])
        if year < 100:
            year += 2000
        if 1 <= month <= 12:
            # Month precision means good through the end of that month.
            return date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    return None


def stock_on_hand(statuses: Optional[list[str]] = DEFAULT_STATUSES) -> dict[str, Any]:
    """Every product/batch holding, with the counts the page reports.

    The flags are computed here rather than in the browser so that "expiring
    soon" means the same thing everywhere, and so it moves with the calendar
    instead of being pinned to a year someone typed once.
    """
    rows = _run(_STOCK_QUERY, statuses=list(statuses) if statuses is not None else None)

    today = date.today()
    horizon = today + timedelta(days=EXPIRING_WITHIN_DAYS)

    items = []
    for row in rows:
        expiry = _parse_expiry(row.get("expiry"))
        quantity = float(row.get("quantity") or 0.0)
        items.append(
            {
                # Stable across reloads because it is derived from the
                # holding itself, not from position in the list.
                "id": f"{row['group_key']}::{row.get('batch_number') or '-'}",
                "product": row.get("product"),
                "product_id": row.get("product_id"),
                "batch": row.get("batch_number"),
                "expiry": row.get("expiry"),
                "quantity": quantity,
                "free_quantity": float(row.get("free_quantity") or 0.0),
                "mrp": row.get("mrp"),
                "gst": row.get("gst"),
                "source_invoice": row.get("latest_invoice"),
                "deliveries": int(row.get("deliveries") or 0),
                "is_low_stock": quantity <= LOW_STOCK_THRESHOLD,
                "is_expired": expiry is not None and expiry < today,
                "is_expiring_soon": expiry is not None and today <= expiry <= horizon,
            }
        )

    return {
        "items": items,
        "stats": {
            "total_skus": len(items),
            "total_quantity": sum(i["quantity"] for i in items),
            "low_stock": sum(1 for i in items if i["is_low_stock"]),
            "expiring_soon": sum(1 for i in items if i["is_expiring_soon"]),
            "expired": sum(1 for i in items if i["is_expired"]),
        },
        "statuses": list(statuses) if statuses is not None else None,
        "low_stock_threshold": LOW_STOCK_THRESHOLD,
        "expiring_within_days": EXPIRING_WITHIN_DAYS,
    }
