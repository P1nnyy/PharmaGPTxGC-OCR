"""The GSTR-3B worksheet.

A worksheet, not a return. It shows what each 3B row should contain and where
that figure came from, so the person filing can check the portal's numbers
against their own records rather than accepting them.

**The outward rows are not editable at the portal.** Since the January 2025
change, Table 3 of GSTR-3B is auto-populated from GSTR-1 and GSTR-1A and locked.
A wrong outward figure cannot be fixed in 3B - it has to be corrected in
**GSTR-1A, before 3B is filed**, and once 3B is filed for the period that route
closes too. This is the single most expensive thing to not know, because the
instinct on seeing a wrong number is to edit it where you found it, and here
that is impossible. Every outward row carries the warning.

The ITC side is different: Table 4 *is* editable, which is exactly why it needs
a worksheet. The figure the portal proposes comes from GSTR-2B; the figure the
shop believes comes from its own purchases; and where those differ, somebody
has to decide which to file. This shows both positions rather than one.
"""

from dataclasses import dataclass, field
from typing import Optional

from core.itc_rules import TABLE_PERMANENT, TABLE_RECLAIM, TABLE_TEMPORARY
from services.statutory.model import Drill, DrillKind, Figure, ReportRow

# Shown against every auto-populated row. Deliberately blunt.
AUTO_POPULATED_WARNING = (
    "Auto-populated from GSTR-1/1A at the portal and NOT editable there. If this "
    "figure is wrong, correct it in GSTR-1A before filing 3B - it cannot be "
    "changed in 3B itself, and once 3B is filed for this period that route closes."
)

ITC_EDITABLE_NOTE = (
    "Table 4 is editable at the portal, and the portal proposes GSTR-2B's figure. "
    "Where that differs from this one, the difference has to be explained before "
    "it is overridden."
)


@dataclass
class Gstr3bRow:
    code: str
    label: str
    taxable: Optional[Figure] = None
    igst: Optional[Figure] = None
    cgst: Optional[Figure] = None
    sgst: Optional[Figure] = None
    cess: Optional[Figure] = None
    auto_populated: bool = False
    note: str = ""
    caveats: tuple = ()

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "taxable": self.taxable.to_dict() if self.taxable else None,
            "igst": self.igst.to_dict() if self.igst else None,
            "cgst": self.cgst.to_dict() if self.cgst else None,
            "sgst": self.sgst.to_dict() if self.sgst else None,
            "cess": self.cess.to_dict() if self.cess else None,
            "auto_populated": self.auto_populated,
            "note": self.note,
            "caveats": list(self.caveats),
        }


@dataclass
class Gstr3bWorksheet:
    period_label: str
    months: tuple
    outward: list = field(default_factory=list)
    itc: list = field(default_factory=list)
    itc_source: dict = field(default_factory=dict)
    net_itc: Optional[Gstr3bRow] = None

    def to_dict(self) -> dict:
        return {
            "period_label": self.period_label,
            "months": list(self.months),
            "outward": [r.to_dict() for r in self.outward],
            "itc": [r.to_dict() for r in self.itc],
            "net_itc": self.net_itc.to_dict() if self.net_itc else None,
            "itc_source": self.itc_source,
            "auto_populated_warning": AUTO_POPULATED_WARNING,
        }


def _outward_rows(gstr1, months: tuple) -> list:
    """Table 3.1, from the GSTR-1 the same period produced.

    Read off the C1 engine's totals rather than recomputed, so the 3B worksheet
    and the GSTR-1 preview cannot disagree - which is the first thing an
    officer compares.
    """
    totals = gstr1.totals
    sales_drill = Drill(
        kind=DrillKind.SALES,
        filters={"periods": list(months), "status": "CONFIRMED"},
        count=totals.get("document_count"),
    )

    taxable_row = Gstr3bRow(
        code="3.1(a)",
        label="Outward taxable supplies (other than zero rated, nil rated and exempted)",
        taxable=Figure(totals["taxable_paise"], sales_drill),
        igst=Figure(totals["igst_paise"], sales_drill),
        cgst=Figure(totals["cgst_paise"], sales_drill),
        sgst=Figure(totals["sgst_paise"], sales_drill),
        cess=Figure(totals["cess_paise"], sales_drill),
        auto_populated=True,
        note="From Tables 4A, 5 and 7 of this period's GSTR-1.",
    )

    # Nil-rated and exempt together, which is what 3.1(c) asks for even though
    # Table 8 keeps them apart. Non-GST is deliberately not folded in here -
    # it has its own row, and adding it would overstate 3.1(c).
    nil_exempt = 0
    non_gst = 0
    for row in gstr1.tables["nil_exempt"]:
        nil_exempt += row.nil_rated_paise + row.exempted_paise
        non_gst += row.non_gst_paise

    untaxed_drill = Drill(kind=DrillKind.SALES, filters={"periods": list(months), "untaxed": True})

    rows = [
        taxable_row,
        Gstr3bRow(
            code="3.1(c)",
            label="Other outward supplies (nil rated, exempted)",
            taxable=Figure(nil_exempt, untaxed_drill),
            auto_populated=True,
            note="From Table 8 of this period's GSTR-1. Nil-rated and exempt are "
                 "separate rows there and combine here, which is what 3.1(c) asks for.",
        ),
        Gstr3bRow(
            code="3.1(e)",
            label="Non-GST outward supplies",
            taxable=Figure(non_gst, untaxed_drill),
            auto_populated=True,
            note="Also from Table 8. Reported separately from 3.1(c) - folding "
                 "non-GST supplies into the exempt row would overstate it.",
        ),
    ]
    for row in rows:
        row.caveats = (AUTO_POPULATED_WARNING,)
    return rows


def _itc_rows(claim, reversal_totals: dict, months: tuple) -> list:
    """Table 4, from the ITC source and the reversal ledger."""

    def reversal_figure(table: str, field_name: str) -> Figure:
        bucket = reversal_totals.get(table) or {}
        return Figure(
            paise=int(bucket.get(field_name) or 0),
            drill=Drill(
                kind=DrillKind.ITC_REVERSALS,
                filters={"periods": list(months), "gstr3b_table": table},
                count=len(bucket.get("reversal_ids") or ()),
            ),
        )

    available = Gstr3bRow(
        code="4(A)(5)",
        label="All other ITC",
        igst=claim.igst,
        cgst=claim.cgst,
        sgst=claim.sgst,
        cess=claim.cess,
        note=ITC_EDITABLE_NOTE,
        caveats=tuple(claim.caveats),
    )

    permanent = Gstr3bRow(
        code=TABLE_PERMANENT,
        label="ITC reversed — rules 38, 42 & 43 and section 17(5)",
        igst=reversal_figure(TABLE_PERMANENT, "igst_paise"),
        cgst=reversal_figure(TABLE_PERMANENT, "cgst_paise"),
        sgst=reversal_figure(TABLE_PERMANENT, "sgst_paise"),
        cess=reversal_figure(TABLE_PERMANENT, "cess_paise"),
        note="Permanent. Expired stock written off under 17(5)(h) is the usual "
             "case for a pharmacy, and it can never be reclaimed.",
    )

    temporary = Gstr3bRow(
        code=TABLE_TEMPORARY,
        label="ITC reversed — others",
        igst=reversal_figure(TABLE_TEMPORARY, "igst_paise"),
        cgst=reversal_figure(TABLE_TEMPORARY, "cgst_paise"),
        sgst=reversal_figure(TABLE_TEMPORARY, "sgst_paise"),
        cess=reversal_figure(TABLE_TEMPORARY, "cess_paise"),
        note="Temporary. Rule 37's 180-day non-payment reversal is reclaimed in "
             "4(D)(1) once the supplier is paid.",
    )

    reclaim = Gstr3bRow(
        code=TABLE_RECLAIM,
        label="ITC reclaimed which was reversed under 4(B)(2) in an earlier period",
        igst=reversal_figure(TABLE_RECLAIM, "igst_paise"),
        cgst=reversal_figure(TABLE_RECLAIM, "cgst_paise"),
        sgst=reversal_figure(TABLE_RECLAIM, "sgst_paise"),
        cess=reversal_figure(TABLE_RECLAIM, "cess_paise"),
        note="Each reclaim names the reversal it undoes, so the credit can be "
             "traced back to the period it was given up in.",
    )

    return [available, permanent, temporary, reclaim]


def _net_itc(itc_rows: list) -> Gstr3bRow:
    """4(C): available less reversed.

    The reclaim in 4(D)(1) is *not* added here. It is a disclosure of what came
    back, and the credit itself already sits inside 4(A)(5) for the period it
    was reclaimed in - adding it again would claim it twice.
    """
    available, permanent, temporary, _reclaim = itc_rows

    def net(field_name: str) -> Figure:
        got = getattr(available, field_name) or Figure(0)
        back = (getattr(permanent, field_name) or Figure(0)).paise
        back += (getattr(temporary, field_name) or Figure(0)).paise
        return Figure(got.paise - back, None, got.caveat)

    return Gstr3bRow(
        code="4(C)",
        label="Net ITC available (A) − (B)",
        igst=net("igst"),
        cgst=net("cgst"),
        sgst=net("sgst"),
        cess=net("cess"),
        note="4(D)(1) is deliberately not added in: a reclaim is a disclosure, "
             "and the credit itself is already inside 4(A)(5) for the period it "
             "was reclaimed in.",
    )


def build_worksheet(gstr1, claim, reversal_totals: dict, filing_period) -> Gstr3bWorksheet:
    """The whole worksheet for one filing period."""
    months = tuple(filing_period.months)
    itc_rows = _itc_rows(claim, reversal_totals or {}, months)
    return Gstr3bWorksheet(
        period_label=filing_period.label,
        months=months,
        outward=_outward_rows(gstr1, months),
        itc=itc_rows,
        net_itc=_net_itc(itc_rows),
        itc_source={
            "name": claim.source_name,
            "is_authoritative": claim.is_authoritative,
            "caveats": list(claim.caveats),
            "counted_invoices": claim.counted_invoices,
            "excluded": [dict(e) for e in claim.excluded],
        },
    )
