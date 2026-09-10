"""Reading a filing period's sales, in the shape the return engine wants.

The boundary between the graph and the engine. Cypher stops here; everything
past this module works on the frozen structures in `services/gstr1/model.py`
and can be tested without a database.

One judgement is made in this module rather than in the engine, and it is worth
being explicit about because it fills in a figure nobody typed.

An over-the-counter sale is supplied where the counter stands. That is not an
assumption - it is what the place of supply *is* for a supply of goods that the
customer takes away with them, however far they travelled to buy it. So a
COUNTER bill or a DAY_TOTAL with no place of supply recorded is read as
intra-state, and the shop's own state code is filled in.

A photographed or imported bill gets no such treatment. Those can be
deliveries, and a delivery is supplied where it is sent. Where the source did
not say, the field stays empty and the validation report raises it - which is
the whole reason `place_of_supply_state_code` is nullable rather than defaulted
in the repository.
"""

from decimal import Decimal
from typing import Optional

from core.hsn import normalize_uqc
from core.tax_periods import financial_year_of_period, period_bounds
from core.tenancy import current_tenant
from db.graph_db import get_driver
from db.repositories import pharmacy_repository
from services.gstr1.model import (
    DocumentStatus,
    OutwardDocument,
    OutwardLine,
    RateBlock,
    SupplyClass,
    quantity as to_quantity,
)

# Capture modes where the supply happened at the counter, so the place of
# supply is the shop's own state by definition rather than by assumption.
_OVER_THE_COUNTER = {"COUNTER", "DAY_TOTAL"}


def _run_read(query: str, **params) -> list:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def _int(value) -> int:
    """Paise, defensively. A property that was never written reads as None."""
    return int(value or 0)


def _line(row: dict) -> OutwardLine:
    supply_class = row.get("supply_class") or SupplyClass.TAXABLE
    if supply_class not in SupplyClass.ALL:
        supply_class = SupplyClass.TAXABLE
    return OutwardLine(
        line_id=row.get("line_id") or row.get("id"),
        product_id=row.get("product_id"),
        product_name=row.get("product_name"),
        hsn=row.get("hsn"),
        # Normalised on the way out rather than on the way in: the counter
        # records what the pack says ("strip"), and the portal's vocabulary is
        # a reporting concern. Storing the mapped value would lose what was
        # actually on the shelf.
        uqc=normalize_uqc(row.get("uqc")),
        quantity=to_quantity(row.get("quantity")),
        supply_class=supply_class,
        rate_bp=_int(row.get("rate_bp")),
        taxable_paise=_int(row.get("taxable_paise")),
        cgst_paise=_int(row.get("cgst_paise")),
        sgst_paise=_int(row.get("sgst_paise")),
        igst_paise=_int(row.get("igst_paise")),
        cess_paise=_int(row.get("cess_paise")),
    )


def _rate_block(row: dict) -> RateBlock:
    return RateBlock(
        rate_bp=_int(row.get("rate_bp")),
        taxable_paise=_int(row.get("taxable_paise")),
        cgst_paise=_int(row.get("cgst_paise")),
        sgst_paise=_int(row.get("sgst_paise")),
        igst_paise=_int(row.get("igst_paise")),
        cess_paise=_int(row.get("cess_paise")),
    )


def _document(row: dict, own_state_code: Optional[str]) -> OutwardDocument:
    sale = dict(row["sale"])
    capture_mode = sale.get("capture_mode") or "COUNTER"

    place_of_supply = sale.get("place_of_supply_state_code")
    if not place_of_supply and capture_mode in _OVER_THE_COUNTER:
        place_of_supply = own_state_code

    status = sale.get("status") or DocumentStatus.CONFIRMED
    if status not in DocumentStatus.ALL:
        status = DocumentStatus.DRAFT

    return OutwardDocument(
        document_id=sale["id"],
        sale_date=sale.get("sale_date") or "",
        tax_period=sale.get("tax_period") or "",
        supplier_state_code=own_state_code or "",
        bill_number=sale.get("bill_number") or sale.get("serial"),
        series_prefix=sale.get("series_prefix"),
        serial_sequence=(
            int(sale["serial_sequence"]) if sale.get("serial_sequence") is not None else None
        ),
        document_type=sale.get("document_type") or "INVOICE",
        document_class=sale.get("document_class") or "INVOICE_CUM_BILL_OF_SUPPLY",
        capture_mode=capture_mode,
        status=status,
        place_of_supply_state_code=place_of_supply,
        customer_gstin=sale.get("customer_gstin"),
        customer_name=sale.get("customer_name"),
        lines=tuple(_line(r) for r in (row.get("lines") or []) if r),
        rate_blocks=tuple(_rate_block(r) for r in (row.get("rate_blocks") or []) if r),
        exempt_paise=_int(sale.get("exempt_paise")),
        nil_rated_paise=_int(sale.get("nil_rated_paise")),
        non_gst_paise=_int(sale.get("non_gst_paise")),
        taxable_paise=_int(sale.get("taxable_paise")),
        cgst_paise=_int(sale.get("cgst_paise")),
        sgst_paise=_int(sale.get("sgst_paise")),
        igst_paise=_int(sale.get("igst_paise")),
        cess_paise=_int(sale.get("cess_paise")),
        round_off_paise=_int(sale.get("round_off_paise")),
        grand_total_paise=_int(sale.get("grand_total_paise")),
        is_aggregate=bool(sale.get("is_aggregate")),
        reverses_document_id=sale.get("reverses_document_id"),
        notes=sale.get("notes"),
    )


def documents_for_window(
    start_date: str,
    end_date: str,
    own_state_code: Optional[str] = None,
    pharmacy_id: Optional[str] = None,
) -> list:
    """Every sale in a date window, as outward documents.

    Deliberately unfiltered by status. Drafts and cancellations are read and
    the engine decides what each table does with them - Table 13 counts a
    cancelled bill, every other table ignores it - because a filter here would
    make that decision once, invisibly, for all of them.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    if own_state_code is None:
        own_state_code = (pharmacy_repository.get_profile(pharmacy_id) or {}).get("state_code")

    rows = _run_read(
        """
        MATCH (s:Sale {pharmacy_id: $pharmacy_id})
        WHERE s.sale_date >= $start AND s.sale_date <= $end
        OPTIONAL MATCH (s)-[:HAS_LINE]->(l:SaleLine)
        OPTIONAL MATCH (s)-[:HAS_RATE_BLOCK]->(b:SaleRateBlock)
        RETURN s {.*} AS sale,
               collect(DISTINCT l {.*}) AS lines,
               collect(DISTINCT b {.*}) AS rate_blocks
        ORDER BY sale.sale_date, sale.serial_sequence
        """,
        pharmacy_id=pharmacy_id,
        start=start_date,
        end=end_date,
    )
    return [_document(row, own_state_code) for row in rows]


def documents_for_period(filing_period, pharmacy_id: Optional[str] = None) -> list:
    """Every sale in a filing window - one month, or a QRMP quarter."""
    return documents_for_window(
        filing_period.start_date, filing_period.end_date, pharmacy_id=pharmacy_id
    )


def own_sales_for_financial_year(period: str, pharmacy_id: Optional[str] = None) -> int:
    """What this workspace has recorded in the financial year, in paise.

    A floor under aggregate turnover and never the figure itself: AATO is
    PAN-wide and this is one GSTIN. Used only to notice that a declared
    turnover is already contradicted by what we can see, which is how a stale
    declaration gets caught before it files four HSN digits instead of six.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    financial_year = financial_year_of_period(period)
    start, _ = period_bounds(f"04{financial_year:04d}")
    _, end = period_bounds(f"03{financial_year + 1:04d}")

    rows = _run_read(
        """
        MATCH (s:Sale {pharmacy_id: $pharmacy_id, status: 'CONFIRMED'})
        WHERE s.sale_date >= $start AND s.sale_date <= $end
          AND coalesce(s.document_type, 'INVOICE') = 'INVOICE'
        RETURN sum(
            coalesce(s.taxable_paise, 0) + coalesce(s.exempt_paise, 0)
            + coalesce(s.nil_rated_paise, 0) + coalesce(s.non_gst_paise, 0)
        ) AS total
        """,
        pharmacy_id=pharmacy_id,
        start=start,
        end=end,
    )
    return _int(rows[0].get("total")) if rows else 0
