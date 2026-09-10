"""The vendor filing scorecard.

What a shopkeeper actually wants to know about a distributor is not its
turnover with them. It is: **does this supplier's paperwork cost me money?**
A distributor who files GSTR-1 late holds up the buyer's input credit, because
credit is capped by what appears in GSTR-2B and nothing appears there until the
supplier files. The buyer pays cash that month and gets the credit whenever the
supplier gets round to it.

That is a real cost and nobody currently measures it. This report does - or
will, once GSTR-2B is wired in.

**What is real today and what is not.** Filing dates come from GSTR-2B, which
this system does not yet fetch. So every filing figure here is `None` and the
report says so per row, rather than showing a zero that reads as "always on
time". What *is* real today is the purchase side: how much was bought, how much
credit each supplier accounts for, and therefore how much is exposed to their
filing behaviour. That much is worth showing on its own.

The seam is the same shape as the one in `services/statutory/itc_sources.py`:
a source answers for filing history, `has_filing_data` says whether to believe
it, and the report renders whatever it is given. Wiring 2B in means
implementing one class - the phrasing, the ranking and the UI do not move.
"""

from dataclasses import dataclass, field
from typing import Optional, Protocol

from core.money import paise_from_legacy_rupees


@dataclass
class FilingHistory:
    """One distributor's GSTR-1 filing behaviour over the window."""

    vendor_id: str
    periods_expected: int = 0
    periods_filed_on_time: int = 0
    periods_filed_late: int = 0
    periods_not_filed: int = 0
    average_delay_days: Optional[float] = None
    blocked_credit_paise: int = 0

    @property
    def on_time_rate(self) -> Optional[float]:
        if not self.periods_expected:
            return None
        return round(self.periods_filed_on_time * 100 / self.periods_expected, 1)


class FilingSource(Protocol):
    """Anything that can say how a distributor has been filing."""

    name: str
    has_filing_data: bool

    def history_for(self, vendor_ids: list, months: list) -> dict:
        """`vendor_id -> FilingHistory`."""
        ...


@dataclass
class NoFilingDataSource:
    """Today's source: the purchase side only.

    Returns an empty history for every vendor rather than zeros. A zero would
    render as "filed on time, every month", which is a claim about a supplier
    we have no evidence for - and the kind of claim somebody would repeat to
    the supplier.
    """

    name: str = "PURCHASE_RECORDS_ONLY"
    has_filing_data: bool = False

    def history_for(self, vendor_ids: list, months: list) -> dict:
        return {vendor_id: FilingHistory(vendor_id=vendor_id) for vendor_id in vendor_ids}


@dataclass
class Gstr2bFilingSource:
    """Filing history from GSTR-2B. Not yet wired.

    A real class rather than a comment, so the shape of the swap is fixed now.
    It raises rather than returning empties: a source that silently answered
    "no delays" would tell a shop its suppliers were fine on no evidence.
    """

    name: str = "GSTR_2B"
    has_filing_data: bool = True

    def history_for(self, vendor_ids: list, months: list) -> dict:
        raise NotImplementedError(
            "GSTR-2B is not wired up yet, so filing dates are unknown. The "
            "scorecard reports the purchase exposure and says the filing "
            "columns are unavailable."
        )


def default_source() -> FilingSource:
    """One line to change when 2B lands."""
    return NoFilingDataSource()


def _sentence(name: str, history: FilingHistory, blocked_rupees: float) -> Optional[str]:
    """The finding, phrased for a shopkeeper rather than an accountant.

    "On-time filing rate 66.7%" is a statistic. "Filed late in 4 of the last 6
    months, delaying ₹42,000 of your credit by an average of 31 days" is
    something you can take to the distributor.
    """
    if not history.periods_expected:
        return None
    late = history.periods_filed_late + history.periods_not_filed
    if not late:
        return (
            f"{name} filed on time in all {history.periods_expected} of the last "
            f"{history.periods_expected} months."
        )
    delay = (
        f" by an average of {history.average_delay_days:.0f} days"
        if history.average_delay_days else ""
    )
    money = f" ₹{blocked_rupees:,.0f} of your credit" if blocked_rupees else " your credit"
    return (
        f"{name} filed late in {late} of the last {history.periods_expected} months, "
        f"delaying{money}{delay}."
    )


@dataclass
class VendorScore:
    vendor_id: str
    name: str
    gstin: Optional[str]
    invoice_count: int
    purchase_taxable_paise: int
    credit_paise: int
    return_window_days: Optional[int]
    history: FilingHistory
    has_filing_data: bool

    def to_dict(self) -> dict:
        blocked_rupees = round(self.history.blocked_credit_paise / 100, 2)
        return {
            "vendor_id": self.vendor_id,
            "name": self.name,
            "gstin": self.gstin,
            "invoice_count": self.invoice_count,
            "purchase_taxable": round(self.purchase_taxable_paise / 100, 2),
            # What this supplier accounts for. Real today, and the measure of
            # how much their filing behaviour can cost.
            "credit_from_this_supplier": round(self.credit_paise / 100, 2),
            "return_window_days": self.return_window_days,
            "filing": {
                "available": self.has_filing_data,
                "on_time_rate": self.history.on_time_rate,
                "periods_expected": self.history.periods_expected,
                "periods_filed_late": self.history.periods_filed_late,
                "periods_not_filed": self.history.periods_not_filed,
                "average_delay_days": self.history.average_delay_days,
                "blocked_credit": blocked_rupees,
            },
            "summary": (
                _sentence(self.name, self.history, blocked_rupees)
                if self.has_filing_data
                else (
                    f"{self.name} accounts for ₹{self.credit_paise / 100:,.0f} of your "
                    "input credit this period. Whether they file on time is not known "
                    "yet — that needs GSTR-2B."
                )
            ),
        }


def build(vendor_totals: list, months: list, source: Optional[FilingSource] = None) -> dict:
    """The scorecard. Real purchase exposure now, filing columns when 2B lands."""
    source = source or default_source()
    vendor_ids = [row["vendor_id"] for row in vendor_totals if row.get("vendor_id")]
    histories = source.history_for(vendor_ids, list(months))

    scores = []
    for row in vendor_totals:
        vendor_id = row.get("vendor_id")
        if not vendor_id:
            continue
        scores.append(
            VendorScore(
                vendor_id=vendor_id,
                name=row.get("name") or "Unnamed distributor",
                gstin=row.get("gstin"),
                invoice_count=int(row.get("invoice_count") or 0),
                # Invoice headers are still float rupees; converted once here.
                purchase_taxable_paise=paise_from_legacy_rupees(row.get("taxable_rupees")) or 0,
                credit_paise=paise_from_legacy_rupees(row.get("tax_rupees")) or 0,
                return_window_days=row.get("return_window_days"),
                history=histories.get(vendor_id) or FilingHistory(vendor_id=vendor_id),
                has_filing_data=source.has_filing_data,
            )
        )

    # Ranked by how much credit rides on them, which is the order in which a
    # supplier's filing behaviour matters.
    scores.sort(key=lambda s: s.credit_paise, reverse=True)

    return {
        "rows": [s.to_dict() for s in scores],
        "row_count": len(scores),
        "source": {
            "name": source.name,
            "has_filing_data": source.has_filing_data,
            "note": (
                None if source.has_filing_data else
                "Filing dates come from GSTR-2B, which is not connected yet. Until it "
                "is, this shows what each distributor accounts for — the credit that "
                "would be held up if they filed late — and leaves the filing columns "
                "blank rather than showing zeros that would read as a clean record."
            ),
        },
        "totals": {
            "credit_at_stake": round(sum(s.credit_paise for s in scores) / 100, 2),
            "vendor_count": len(scores),
            "missing_return_window_count": sum(
                1 for s in scores if s.return_window_days is None
            ),
        },
    }
