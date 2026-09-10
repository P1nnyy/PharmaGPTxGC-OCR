"""The statutory report pack: seven reports over one filing period.

One entry point, because the reports are not independent. The 3B worksheet
reads the GSTR-1 the same period produced; the cross-checks compare the return
against the register; the HSN summary is the return's Table 12 with validation
attached. Building them separately would let two reports disagree about the
same month, which is precisely the failure the cross-checks exist to catch -
and catching your own bug with your own checker is not the intended use.

So the period is loaded once, the return is computed once, and every report is
a projection of that. If two reports differ, it is because the records differ,
not because two code paths drifted.
"""

from dataclasses import dataclass, field
from typing import Optional

from core.itc_rules import TABLE_PERMANENT, TABLE_RECLAIM, TABLE_TEMPORARY
from services.gstr1.engine import compute
from services.statutory import crosschecks, hsn as hsn_reports, registers
from services.statutory.gstr3b import build_worksheet
from services.statutory.itc_sources import default_source
from services.statutory.model import Drill, DrillKind, Figure, ReportRow

# The seven reports, in the order the UI shows them and the order somebody
# works through them: what is being filed, then what it was built from, then
# what has to be explained.
REPORT_IDS = (
    "gstr1",
    "gstr3b",
    "purchase_register",
    "sales_register",
    "hsn_summary",
    "document_series",
    "itc_reversals",
)


def document_series(gstr1) -> dict:
    """Table 13, with gaps and duplicates called out.

    The same aggregation the return files, presented for a person rather than
    for the portal: a series with a hole in it is the row somebody has to
    explain, so it is flagged rather than left to be spotted in a column of
    numbers.
    """
    rows = []
    for series in gstr1.tables["documents"].series:
        flags = []
        if series.gaps:
            flags.append("GAP")
        if series.duplicates:
            flags.append("DUPLICATE")
        rows.append(
            ReportRow(
                cells={
                    "series_prefix": series.series_prefix,
                    "opening_number": series.opening_number,
                    "closing_number": series.closing_number,
                    "total_issued": series.total_issued,
                    "cancelled": series.cancelled,
                    "net_issued": series.net_issued,
                    "gaps": series.gaps,
                    "duplicates": series.duplicates,
                },
                flags=tuple(flags),
            ).to_dict()
        )
    return {
        "rows": rows,
        "row_count": len(rows),
        "has_gaps": gstr1.tables["documents"].has_gaps,
        "has_duplicates": gstr1.tables["documents"].has_duplicates,
        "documents_without_series": list(gstr1.tables["documents"].documents_without_series),
    }


def itc_reversal_register(reversals: list) -> dict:
    """Report 7: every reversal, with the reason it can be defended by.

    Each row carries its trigger, the provision behind it, the 3B row it was
    reported in, and a link to the source document. Those four together are
    what turns a number into an answer.
    """
    rows = []
    by_table = {TABLE_PERMANENT: 0, TABLE_TEMPORARY: 0, TABLE_RECLAIM: 0}

    for reversal in reversals:
        table = reversal.get("gstr3b_table")
        if table in by_table:
            by_table[table] += int(reversal.get("total_paise") or 0)

        source_id = reversal.get("source_id")
        drill = (
            Drill(kind=DrillKind.PURCHASES, filters={"ids": [source_id]}, count=1)
            if reversal.get("source_type") == "INVOICE" and source_id
            else Drill(kind=DrillKind.ITC_REVERSALS, filters={"ids": [reversal.get("id")]}, count=1)
        )

        rows.append(
            ReportRow(
                cells={
                    "id": reversal.get("id"),
                    "tax_period": reversal.get("tax_period"),
                    "trigger": reversal.get("trigger"),
                    "statutory_reference": reversal.get("statutory_reference"),
                    "gstr3b_table": table,
                    "reason": reversal.get("reason"),
                    "is_permanent": reversal.get("is_permanent"),
                    "cgst": Figure(int(reversal.get("cgst_paise") or 0), drill),
                    "sgst": Figure(int(reversal.get("sgst_paise") or 0), drill),
                    "igst": Figure(int(reversal.get("igst_paise") or 0), drill),
                    "cess": Figure(int(reversal.get("cess_paise") or 0), drill),
                    "total": Figure(int(reversal.get("total_paise") or 0), drill),
                    "source_type": reversal.get("source_type"),
                    "source_id": source_id,
                    "source_invoice_number": reversal.get("source_invoice_number"),
                    "source_seller_name": reversal.get("source_seller_name"),
                    "reclaims_id": reversal.get("reclaims_id"),
                    "note": reversal.get("note"),
                    "recorded_at": reversal.get("recorded_at"),
                },
                drill=drill,
                flags=("RECLAIM",) if reversal.get("reclaims_id") else (),
            ).to_dict()
        )

    return {
        "rows": rows,
        "row_count": len(rows),
        "totals": {
            "permanent": Figure(by_table[TABLE_PERMANENT]).to_dict(),
            "temporary": Figure(by_table[TABLE_TEMPORARY]).to_dict(),
            "reclaimed": Figure(by_table[TABLE_RECLAIM]).to_dict(),
        },
        "note": (
            "Every row names the rule it was reversed under and the document it "
            "came from. A reversal that cannot answer both is not defensible."
        ),
    }


@dataclass
class ReportPack:
    period: dict
    shop: dict
    reports: dict = field(default_factory=dict)
    cross_checks: list = field(default_factory=list)

    @property
    def failing_checks(self) -> list:
        return [c for c in self.cross_checks if not c.agrees]

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "shop": self.shop,
            "reports": self.reports,
            "cross_checks": [c.to_dict() for c in self.cross_checks],
            "checks_pass": not self.failing_checks,
            "failing_check_count": len(self.failing_checks),
        }


def build(
    identity: dict,
    filing_period,
    documents: list,
    payments: list,
    purchase_invoices: list,
    purchase_rate_blocks: list,
    purchase_hsn_lines: list,
    reversals: list,
    reversal_totals: dict,
    own_sales_paise: Optional[int] = None,
    itc_source=None,
    sales_filters: Optional[dict] = None,
) -> ReportPack:
    """Every report for one filing period, from one load of the records."""
    months = tuple(filing_period.months)
    sales_filters = sales_filters or {}

    # The return, computed once. Every outward report is a projection of this.
    gstr1 = compute(documents, identity, filing_period, own_sales_paise=own_sales_paise)

    sales_reg = registers.sales_register(
        documents,
        payments,
        rate_bp=sales_filters.get("rate_bp"),
        capture_mode=sales_filters.get("capture_mode"),
        payment_method=sales_filters.get("payment_method"),
    )
    purchase_reg = registers.purchase_register(purchase_invoices, purchase_rate_blocks)
    outward_hsn = hsn_reports.outward_summary(gstr1, months)
    inward_hsn = hsn_reports.inward_summary(purchase_hsn_lines)

    source = itc_source or default_source()
    claim = source.claim_for(list(months), purchase_invoices)
    worksheet = build_worksheet(gstr1, claim, reversal_totals, filing_period)

    reports = {
        "gstr1": {
            # Converted to rupees at this boundary, and the `_paise` suffix
            # dropped with the conversion - a key named `_paise` holding
            # rupees is exactly the confusion the naming rule exists to stop.
            "totals": {
                (k[:-6] if k.endswith("_paise") else k):
                    (round(v / 100, 2) if k.endswith("_paise") else v)
                for k, v in gstr1.totals.items()
            },
            "tables": _gstr1_tables(gstr1, months),
            "validation": {
                "blocking": [_item(i) for i in gstr1.report.blocking],
                "warnings": [_item(i) for i in gstr1.report.warnings],
            },
            "can_close": gstr1.can_close,
            "is_nil_return": gstr1.is_nil_return,
            "payload": gstr1.payload,
        },
        "gstr3b": worksheet.to_dict(),
        "purchase_register": purchase_reg,
        "sales_register": sales_reg,
        "hsn_summary": {"outward": outward_hsn, "inward": inward_hsn},
        "document_series": document_series(gstr1),
        "itc_reversals": itc_reversal_register(reversals),
    }

    checks = crosschecks.run_all(
        gstr1, sales_reg, outward_hsn, documents, payments, months
    )

    return ReportPack(
        period={
            "label": filing_period.label,
            "frequency": filing_period.frequency,
            "months": list(months),
            "start_date": filing_period.start_date,
            "end_date": filing_period.end_date,
        },
        shop={
            "gstin": identity.get("gstin"),
            "legal_name": identity.get("legal_name"),
            "trade_name": identity.get("trade_name"),
            "state_code": identity.get("state_code"),
            "filing_frequency": identity.get("filing_frequency"),
            "hsn_digits": identity.get("hsn_digits"),
        },
        reports=reports,
        cross_checks=checks,
    )


def _item(item) -> dict:
    return {
        "id": item.id,
        "code": item.code,
        "severity": item.severity,
        "message": item.message,
        "record_type": item.record_type,
        "record_id": item.record_id,
        "line_id": item.line_id,
    }


def _gstr1_tables(gstr1, months: tuple) -> dict:
    """The return's tables with a drill on every aggregate."""
    tables = gstr1.tables

    def bucket(b) -> dict:
        drill = Drill(kind=DrillKind.SALES, filters={"ids": list(b.document_ids)},
                      count=len(b.document_ids))
        return {
            "place_of_supply": b.place_of_supply,
            "rate": b.rate_bp / 100,
            "supply_type": b.supply_type,
            "taxable": Figure(b.taxable_paise, drill).to_dict(),
            "cgst": Figure(b.cgst_paise, drill).to_dict(),
            "sgst": Figure(b.sgst_paise, drill).to_dict(),
            "igst": Figure(b.igst_paise, drill).to_dict(),
        }

    def invoice(e) -> dict:
        drill = Drill(kind=DrillKind.SALES, filters={"ids": [e.document_id]}, count=1)
        return {
            "document_id": e.document_id,
            "bill_number": e.bill_number,
            "sale_date": e.sale_date,
            "place_of_supply": e.place_of_supply,
            "customer_gstin": getattr(e, "customer_gstin", None),
            "customer_name": getattr(e, "customer_name", None),
            "invoice_value": Figure(e.invoice_value_paise, drill).to_dict(),
        }

    untaxed_drill = Drill(kind=DrillKind.SALES, filters={"periods": list(months), "untaxed": True})
    return {
        "b2cs": [bucket(b) for b in tables["b2cs"].buckets],
        "b2cs_negative": [bucket(b) for b in tables["b2cs"].negative_buckets],
        "b2cl": [invoice(e) for e in tables["b2cl"]],
        "b2b": [invoice(e) for e in tables["b2b"]],
        "nil_exempt": [
            {
                "code": r.code,
                "description": r.description,
                "nil_rated": Figure(r.nil_rated_paise, untaxed_drill).to_dict(),
                "exempted": Figure(r.exempted_paise, untaxed_drill).to_dict(),
                "non_gst": Figure(r.non_gst_paise, untaxed_drill).to_dict(),
                "total": Figure(r.total_paise, untaxed_drill).to_dict(),
            }
            for r in tables["nil_exempt"]
        ],
    }
