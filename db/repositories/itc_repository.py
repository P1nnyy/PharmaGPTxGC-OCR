"""The ItcReversal ledger. Append-only, and traceable to a document.

One of the three ledgers the house rules name as append-only, and the reason is
the same as for the other two: a reversal that can be edited is a reversal
nobody can audit. If March's figure changes in June, the March return no longer
matches the records behind it, and there is nothing to show an officer that
explains the difference.

So there is no UPDATE here and no DELETE. A row that turns out to be wrong is
superseded: a new row is written, the old one keeps its `superseded_by`, and
both stay. The register shows the live rows; the history is still there for
anyone who asks why the number moved.

Every row carries a `SOURCE_DOCUMENT` edge to whatever caused it - the purchase
invoice whose credit is going back, usually. That edge is what makes the figure
explainable: "this ₹4,000 came off invoice INV-8823, under Section 17(5)(h),
because the stock expired." A reversal with no source document is a number with
no provenance, which the house rules call a bug.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from core.itc_rules import ItcRuleError, ReversalTrigger, describe, is_reclaimable
from core.tax_periods import is_valid_period
from core.tenancy import current_tenant
from db.graph_db import get_driver


class ItcLedgerError(ValueError):
    """Raised when a reversal cannot be recorded as asked."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_write(query: str, **params) -> list:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(lambda tx: [r.data() for r in tx.run(query, **params)])


def _run_read(query: str, **params) -> list:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def record_reversal(
    trigger: str,
    tax_period: str,
    cgst_paise: int = 0,
    sgst_paise: int = 0,
    igst_paise: int = 0,
    cess_paise: int = 0,
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    note: Optional[str] = None,
    recorded_by: Optional[str] = None,
    reclaims_id: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
) -> dict:
    """Appends one reversal. Never updates anything.

    Amounts are positive magnitudes in paise; the direction is implied by the
    trigger, and a reclaim is not a negative reversal but a row of its own in
    a different 3B table. Keeping the sign out of the data means the register
    can be read without knowing which way each row points.

    The rule, the statutory reference and the 3B table are resolved from the
    trigger and **stored on the row** rather than looked up at read time. A
    return filed in March cited a particular provision; if the catalogue is
    later corrected, March's row has to keep saying what March actually said.
    """
    pharmacy_id = pharmacy_id or current_tenant()

    if not is_valid_period(tax_period):
        raise ItcLedgerError(
            f"{tax_period!r} is not a tax period. A reversal has to belong to the "
            "return it is reported in."
        )

    amounts = (cgst_paise, sgst_paise, igst_paise, cess_paise)
    if any(not isinstance(a, int) or isinstance(a, bool) for a in amounts):
        raise ItcLedgerError("Reversal amounts are integer paise.")
    if any(a < 0 for a in amounts):
        raise ItcLedgerError(
            "Reversal amounts are positive magnitudes. A reclaim is its own row "
            "under 4(D)(1), not a negative reversal."
        )
    if not any(amounts):
        raise ItcLedgerError("A reversal of nothing is not a reversal.")

    try:
        rule = describe(trigger)
    except ItcRuleError as error:
        raise ItcLedgerError(str(error))

    if trigger == ReversalTrigger.RECLAIM:
        if not reclaims_id:
            raise ItcLedgerError(
                "A reclaim has to name the reversal it undoes, or there is no way "
                "to show the credit was ever given up."
            )
        original = get_reversal(reclaims_id, pharmacy_id)
        if original is None:
            raise ItcLedgerError("The reversal being reclaimed does not exist.")
        if not is_reclaimable(original.get("trigger")):
            raise ItcLedgerError(
                f"{original.get('gstr3b_table')} reversals are permanent. Reclaiming "
                "one would claim credit on stock that no longer exists."
            )
    elif reclaims_id:
        raise ItcLedgerError("Only a RECLAIM row may point at a reversal it undoes.")

    if not source_id:
        # The house rules: a derived figure with no provenance is a bug. A
        # reversal is the most consequential derived figure there is.
        raise ItcLedgerError(
            "A reversal has to name the document it came from. A figure with no "
            "source document cannot be explained to an officer."
        )

    rows = _run_write(
        """
        MATCH (ph:Pharmacy {id: $pharmacy_id})
        CREATE (r:ItcReversal {
            id: $id,
            pharmacy_id: $pharmacy_id,
            trigger: $trigger,
            statutory_reference: $statutory_reference,
            gstr3b_table: $gstr3b_table,
            reason: $reason,
            is_permanent: $is_permanent,
            tax_period: $tax_period,
            cgst_paise: $cgst_paise,
            sgst_paise: $sgst_paise,
            igst_paise: $igst_paise,
            cess_paise: $cess_paise,
            total_paise: $total_paise,
            source_type: $source_type,
            source_id: $source_id,
            reclaims_id: $reclaims_id,
            note: $note,
            recorded_at: $now,
            recorded_by: $recorded_by,
            superseded_by: null
        })
        CREATE (r)-[:BELONGS_TO]->(ph)
        WITH r
        // The edge that makes the figure explainable. Optional match so a
        // source that is not an Invoice node (a stock write-off, say) still
        // records its id on the row.
        OPTIONAL MATCH (inv:Invoice {id: $source_id})
        FOREACH (_ IN CASE WHEN inv IS NULL THEN [] ELSE [1] END |
            CREATE (r)-[:SOURCE_DOCUMENT]->(inv)
        )
        RETURN r {.*} AS reversal
        """,
        id=str(uuid.uuid4()),
        pharmacy_id=pharmacy_id,
        trigger=trigger,
        statutory_reference=rule["statutory_reference"],
        gstr3b_table=rule["gstr3b_table"],
        reason=rule["reason"],
        is_permanent=rule["is_permanent"],
        tax_period=tax_period,
        cgst_paise=cgst_paise,
        sgst_paise=sgst_paise,
        igst_paise=igst_paise,
        cess_paise=cess_paise,
        total_paise=sum(amounts),
        source_type=source_type,
        source_id=source_id,
        reclaims_id=reclaims_id,
        note=note,
        now=_now(),
        recorded_by=recorded_by,
    )
    if not rows:
        raise ItcLedgerError("That workspace no longer exists.")
    return rows[0]["reversal"]


def supersede(
    reversal_id: str,
    replacement: dict,
    superseded_by_user: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
) -> dict:
    """Corrects a reversal by writing a new row and marking the old one.

    The only way to change a reversal. Both rows survive: the register reads
    the live one, and the superseded one is still there to explain why the
    figure moved.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    existing = get_reversal(reversal_id, pharmacy_id)
    if existing is None:
        raise ItcLedgerError("That reversal does not exist.")
    if existing.get("superseded_by"):
        raise ItcLedgerError(
            "That reversal has already been superseded. Correct the row that "
            "replaced it."
        )

    new_row = record_reversal(
        recorded_by=superseded_by_user, pharmacy_id=pharmacy_id, **replacement
    )
    _run_write(
        """
        MATCH (r:ItcReversal {id: $id, pharmacy_id: $pharmacy_id})
        SET r.superseded_by = $new_id, r.superseded_at = $now
        """,
        id=reversal_id,
        pharmacy_id=pharmacy_id,
        new_id=new_row["id"],
        now=_now(),
    )
    return new_row


def get_reversal(reversal_id: str, pharmacy_id: Optional[str] = None) -> Optional[dict]:
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (r:ItcReversal {id: $id, pharmacy_id: $pharmacy_id})
        RETURN r {.*} AS reversal
        """,
        id=reversal_id,
        pharmacy_id=pharmacy_id,
    )
    return rows[0]["reversal"] if rows else None


def list_reversals(
    periods: Optional[list] = None,
    include_superseded: bool = False,
    pharmacy_id: Optional[str] = None,
) -> list:
    """The ledger for one or more tax periods.

    Superseded rows are excluded by default: the register states what is
    currently claimed. They are available on request, because "why did this
    number change" is a question somebody eventually asks.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (r:ItcReversal {pharmacy_id: $pharmacy_id})
        WHERE ($periods IS NULL OR r.tax_period IN $periods)
          AND ($include_superseded OR r.superseded_by IS NULL)
        OPTIONAL MATCH (r)-[:SOURCE_DOCUMENT]->(inv:Invoice)
        RETURN r {.*} AS reversal,
               inv.invoice_number AS source_invoice_number,
               inv.invoice_date   AS source_invoice_date,
               coalesce(inv.seller_name, '') AS source_seller_name
        ORDER BY reversal.tax_period, reversal.recorded_at
        """,
        pharmacy_id=pharmacy_id,
        periods=list(periods) if periods else None,
        include_superseded=include_superseded,
    )
    return [
        {
            **row["reversal"],
            "source_invoice_number": row.get("source_invoice_number"),
            "source_invoice_date": row.get("source_invoice_date"),
            "source_seller_name": row.get("source_seller_name") or None,
        }
        for row in rows
    ]


def totals_by_table(periods: Optional[list] = None, pharmacy_id: Optional[str] = None) -> dict:
    """Reversal totals keyed by the 3B row they belong in.

    What the 3B worksheet reads for 4(B)(1), 4(B)(2) and 4(D)(1). Summed from
    the ledger rows rather than from a stored total, so it cannot drift from
    the register that explains it.
    """
    totals: dict[str, dict[str, Any]] = {}
    for row in list_reversals(periods, pharmacy_id=pharmacy_id):
        bucket = totals.setdefault(
            row.get("gstr3b_table"),
            {"cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "cess_paise": 0,
             "total_paise": 0, "reversal_ids": []},
        )
        for key in ("cgst_paise", "sgst_paise", "igst_paise", "cess_paise", "total_paise"):
            bucket[key] += int(row.get(key) or 0)
        bucket["reversal_ids"].append(row.get("id"))
    return totals
