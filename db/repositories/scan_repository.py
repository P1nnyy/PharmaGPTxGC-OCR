"""An append-only record of every scan, kept apart from the invoices they made.

Why this exists as its own node
-------------------------------
"How many scans have I run?" cannot be answered by counting invoices. Deleting
an invoice runs DETACH DELETE, so a scan whose invoice was later removed - a
misfire, a duplicate, a test - leaves no trace at all, and the count silently
falls as the pharmacy tidies up. A number that goes DOWN when you delete a
mistake is not a measure of work done; it is a measure of what happens to still
be lying around.

So a ScanEvent is written when the scan happens and is never deleted. It
records the act, not its output. The invoice id is kept as a loose reference
rather than a relationship, precisely so that deleting the invoice cannot
cascade into the ledger: there is no edge for DETACH DELETE to follow.

That also makes the ledger honest about failure. A scan that extracted nothing,
or whose save failed, still happened and still cost an API call - and those are
the ones worth seeing, because a rising failure count is the signal that
something upstream has broken.
"""

from datetime import datetime, timezone
from typing import Optional

from core.config import settings
from core.logger import logger
from db.graph_db import get_driver

# Bucket sizes the UI offers. 'all' is not a bucket - it is the absence of one -
# but it travels with them because it is one of the choices a user makes.
GRANULARITIES = ("day", "month", "year", "all")

# Neo4j's duration/truncation syntax per bucket. Kept here rather than inlined
# so the set of granularities and the way each is computed cannot drift.
_TRUNCATE = {
    "day": "date.truncate('day', e.created_at)",
    "month": "date.truncate('month', e.created_at)",
    "year": "date.truncate('year', e.created_at)",
}


def record_scan(
    pharmacy_id: Optional[str] = None,
    page_count: int = 1,
    invoice_id: Optional[str] = None,
    status: str = "extracted",
    engine: Optional[str] = None,
    filename: Optional[str] = None,
) -> Optional[str]:
    """Writes one ledger row. Never raises: a scan is not worth failing over.

    The caller is midway through returning a successfully extracted invoice.
    Losing the count of that scan is a smaller harm than turning a good upload
    into a 500, so a ledger failure is logged and swallowed.
    """
    pharmacy_id = pharmacy_id or settings.DEFAULT_PHARMACY_ID
    try:
        driver = get_driver()
        with driver.session() as session:
            return session.execute_write(
                _record_tx, pharmacy_id, int(page_count or 1), invoice_id, status, engine, filename
            )
    except Exception as exc:
        logger.warning(f"[SCAN LEDGER] Could not record scan: {exc}")
        return None


def _record_tx(tx, pharmacy_id, page_count, invoice_id, status, engine, filename) -> str:
    record = tx.run(
        """
        CREATE (e:ScanEvent {
            id: randomUUID(),
            pharmacy_id: $pharmacy_id,
            page_count: $page_count,
            invoice_id: $invoice_id,
            status: $status,
            engine: $engine,
            filename: $filename,
            created_at: datetime()
        })
        RETURN e.id AS id
        """,
        pharmacy_id=pharmacy_id,
        page_count=page_count,
        invoice_id=invoice_id,
        status=status,
        engine=engine,
        filename=filename,
    ).single()
    return record["id"]


def link_invoice(scan_id: Optional[str], invoice_id: Optional[str]) -> None:
    """Notes which invoice a scan produced, once the save has succeeded."""
    if not (scan_id and invoice_id):
        return
    try:
        driver = get_driver()
        with driver.session() as session:
            session.execute_write(
                lambda tx: tx.run(
                    "MATCH (e:ScanEvent {id: $id}) SET e.invoice_id = $invoice_id, e.status = 'saved'",
                    id=scan_id,
                    invoice_id=invoice_id,
                )
            )
    except Exception as exc:
        logger.warning(f"[SCAN LEDGER] Could not link scan {scan_id}: {exc}")


def scan_activity(
    granularity: str = "month",
    limit: int = 24,
    pharmacy_id: Optional[str] = None,
) -> dict:
    """Total scans ever, plus a series bucketed at the requested size.

    total is deliberately unfiltered by the series window: it answers "how much
    work has this pharmacy done", which does not change because the chart is
    showing the last twelve months.
    """
    if granularity not in GRANULARITIES:
        granularity = "month"
    pharmacy_id = pharmacy_id or settings.DEFAULT_PHARMACY_ID

    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(_activity_tx, granularity, int(limit), pharmacy_id)


def _activity_tx(tx, granularity: str, limit: int, pharmacy_id: str) -> dict:
    totals = tx.run(
        """
        MATCH (e:ScanEvent {pharmacy_id: $pharmacy_id})
        RETURN count(e) AS scans,
               sum(coalesce(e.page_count, 1)) AS pages,
               sum(CASE WHEN e.invoice_id IS NULL THEN 1 ELSE 0 END) AS without_invoice,
               min(e.created_at) AS first_scan,
               max(e.created_at) AS last_scan
        """,
        pharmacy_id=pharmacy_id,
    ).single()

    # How many of those scans still have an invoice behind them. The gap
    # between this and the total is the point of the ledger: scans whose
    # invoice was deleted still count as work done.
    surviving = tx.run(
        """
        MATCH (e:ScanEvent {pharmacy_id: $pharmacy_id})
        WHERE e.invoice_id IS NOT NULL
          AND EXISTS { MATCH (inv:Invoice {id: e.invoice_id}) }
        RETURN count(e) AS n
        """,
        pharmacy_id=pharmacy_id,
    ).single()["n"]

    series = []
    if granularity != "all":
        rows = tx.run(
            f"""
            MATCH (e:ScanEvent {{pharmacy_id: $pharmacy_id}})
            WITH {_TRUNCATE[granularity]} AS bucket, e
            RETURN toString(bucket) AS bucket,
                   count(e) AS scans,
                   sum(coalesce(e.page_count, 1)) AS pages
            ORDER BY bucket DESC
            LIMIT $limit
            """,
            pharmacy_id=pharmacy_id,
            limit=limit,
        )
        # Returned oldest-first: a chart reads left to right, and reversing in
        # the client is a step every caller would otherwise have to remember.
        series = [dict(row) for row in rows][::-1]

    def _iso(value):
        return value.iso_format() if hasattr(value, "iso_format") else value

    total = totals["scans"] or 0
    return {
        "granularity": granularity,
        "total_scans": total,
        "total_pages": totals["pages"] or 0,
        "scans_with_invoice": surviving,
        "scans_without_invoice": total - surviving,
        "first_scan": _iso(totals["first_scan"]),
        "last_scan": _iso(totals["last_scan"]),
        "series": series,
    }


def mark_failed(scan_id: Optional[str], error: str) -> None:
    """Records that the scan produced nothing that could be saved."""
    if not scan_id:
        return
    try:
        driver = get_driver()
        with driver.session() as session:
            session.execute_write(
                lambda tx: tx.run(
                    """
                    MATCH (e:ScanEvent {id: $id})
                    SET e.status = 'failed', e.error = $error
                    """,
                    id=scan_id,
                    error=(error or "")[:300],
                )
            )
    except Exception as exc:
        logger.warning(f"[SCAN LEDGER] Could not mark scan {scan_id} failed: {exc}")
