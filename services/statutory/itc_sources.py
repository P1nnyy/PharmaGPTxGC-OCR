"""Where the ITC figure in GSTR-3B 4(A)(5) comes from.

Today it comes from the purchase register - the invoices this shop has scanned.
Eventually it must come from GSTR-2B, because since October 2022 the credit a
taxpayer may claim in 3B is *capped by what the supplier filed*, not by what
the buyer holds. An invoice sitting in a drawer with perfect tax on it earns no
credit until the supplier reports it.

This module exists so that swap is a swap and not a rewrite. Everything
downstream depends on `ItcSource` and `ItcClaim`, never on where the number
came from, and the two things that actually differ between the sources are
carried as data rather than assumed:

  `is_authoritative`  the purchase register is *not*. It is what the shop
                      believes it is owed. 2B is what it may actually claim.
  `caveats`           what a person needs to know before filing on this
                      figure. Empty once 2B is wired in.

The consequence is that the 3B worksheet does not need to know which source it
has. It renders the caveats it is given and marks the figure provisional if it
is told to, so wiring 2B in means implementing one class and changing one
factory line - not touching the worksheet, the exports or the UI.

**The purchase-register figure is an upper bound and is usually wrong.** It
counts everything the shop scanned; 2B counts only what suppliers filed. The
difference is the whole reason reconciliation exists, and reporting it without
saying so would be the most expensive silence in this codebase.
"""

from dataclasses import dataclass, field
from typing import Optional, Protocol

from core.money import paise_from_legacy_rupees
from services.statutory.model import Drill, DrillKind, Figure

# What each source is called on the wire and in the UI.
SOURCE_PURCHASE_REGISTER = "PURCHASE_REGISTER"
SOURCE_GSTR_2B = "GSTR_2B"


@dataclass
class ItcClaim:
    """Eligible input tax credit for a period, and how much to trust it."""

    cgst: Figure
    sgst: Figure
    igst: Figure
    cess: Figure
    source_name: str
    is_authoritative: bool
    caveats: tuple = ()
    # Invoices counted, and those left out with the reason. The second is the
    # more useful number: "we ignored 11 invoices because the supplier GSTIN
    # was missing" is what somebody acts on.
    counted_invoices: int = 0
    excluded: tuple = ()

    @property
    def total_paise(self) -> int:
        return self.cgst.paise + self.sgst.paise + self.igst.paise + self.cess.paise

    def to_dict(self) -> dict:
        return {
            "cgst": self.cgst.to_dict(),
            "sgst": self.sgst.to_dict(),
            "igst": self.igst.to_dict(),
            "cess": self.cess.to_dict(),
            "total": round(self.total_paise / 100, 2),
            "total_paise": self.total_paise,
            "source": self.source_name,
            "is_authoritative": self.is_authoritative,
            "caveats": list(self.caveats),
            "counted_invoices": self.counted_invoices,
            "excluded": [dict(e) for e in self.excluded],
        }


class ItcSource(Protocol):
    """Anything that can answer "what credit may this shop claim this period".

    Deliberately narrow. A source is asked one question and answers with an
    `ItcClaim`; it does not get to decide how the worksheet presents it or
    whether the period may be filed.
    """

    name: str

    def claim_for(self, months: list, invoices: Optional[list] = None) -> ItcClaim:
        """Eligible ITC for the given tax periods."""
        ...


# --------------------------------------------------- the purchase register


# An invoice with no supplier GSTIN earns no credit however clean the rest of
# it is, because there is no registered supplier to have paid the tax. This
# mirrors the rule already used by `services/reports/gst.py` so the two
# registers cannot disagree about the same invoice.
EXCLUSION_NO_GSTIN = "Supplier GSTIN missing"
EXCLUSION_NO_TAX = "No tax on the invoice"


@dataclass
class PurchaseRegisterSource:
    """ITC as the shop's own scanned purchases say it should be.

    Provisional by construction. It is the shop's claim, not the portal's
    confirmation, and every figure it produces is marked as such.
    """

    name: str = SOURCE_PURCHASE_REGISTER

    def claim_for(self, months: list, invoices: Optional[list] = None) -> ItcClaim:
        invoices = list(invoices or [])
        cgst = sgst = igst = cess = 0
        counted = 0
        excluded: list = []

        for invoice in invoices:
            # Purchase-side money is stored as floats and predates the
            # integer-paise rule, so it is converted once here and every
            # figure downstream is exact.
            row_cgst = paise_from_legacy_rupees(invoice.get("cgst")) or 0
            row_sgst = paise_from_legacy_rupees(invoice.get("sgst")) or 0
            row_igst = paise_from_legacy_rupees(invoice.get("igst")) or 0
            row_cess = paise_from_legacy_rupees(invoice.get("cess")) or 0
            tax = row_cgst + row_sgst + row_igst + row_cess

            if not invoice.get("seller_gstin"):
                excluded.append({
                    "invoice_id": invoice.get("invoice_id"),
                    "invoice_number": invoice.get("invoice_number"),
                    "reason": EXCLUSION_NO_GSTIN,
                    "tax_paise": tax,
                })
                continue
            if tax == 0:
                excluded.append({
                    "invoice_id": invoice.get("invoice_id"),
                    "invoice_number": invoice.get("invoice_number"),
                    "reason": EXCLUSION_NO_TAX,
                    "tax_paise": 0,
                })
                continue

            cgst += row_cgst
            sgst += row_sgst
            igst += row_igst
            cess += row_cess
            counted += 1

        caveat = (
            "Provisional: from this shop's own purchase records, not from GSTR-2B."
        )
        drill = Drill(
            kind=DrillKind.PURCHASES,
            filters={"periods": list(months), "itc_eligible": True},
            count=counted,
        )
        return ItcClaim(
            cgst=Figure(cgst, drill, caveat),
            sgst=Figure(sgst, drill, caveat),
            igst=Figure(igst, drill, caveat),
            cess=Figure(cess, drill, caveat),
            source_name=self.name,
            is_authoritative=False,
            caveats=(
                "This figure is what the shop's own scanned purchases add up to. "
                "Since October 2022 the credit claimable in 3B is capped by GSTR-2B "
                "- what suppliers actually filed - so the real figure is usually "
                "lower and never higher.",
                "Reconcile against GSTR-2B before filing. Claiming the purchase "
                "register figure without checking is the most common cause of a "
                "credit demand later.",
                "Purchase amounts are rounded to the nearest paisa from stored "
                "decimal values, which predate this system's integer-paise rule.",
            ),
            counted_invoices=counted,
            excluded=tuple(excluded),
        )


# ------------------------------------------------------------- GSTR-2B


@dataclass
class Gstr2bSource:
    """ITC as GSTR-2B reports it. Not yet wired.

    Present as a real class rather than a comment so the shape of the swap is
    fixed now: when 2B arrives, this implements `claim_for` against the fetched
    statement, `default_source` returns it, and nothing else in the package
    changes. `is_authoritative` becomes True and the caveats fall away on their
    own, which is exactly the behaviour difference the worksheet already
    renders.

    It raises rather than returning zeros. A source that silently answered
    "nil" would file a return claiming no credit at all.
    """

    name: str = SOURCE_GSTR_2B
    statement: Optional[dict] = field(default=None)

    def claim_for(self, months: list, invoices: Optional[list] = None) -> ItcClaim:
        raise NotImplementedError(
            "GSTR-2B is not wired up yet. 4(A)(5) is sourced from the purchase "
            "register in the meantime, and marked provisional."
        )


def default_source() -> ItcSource:
    """The source 4(A)(5) currently uses.

    One line to change when 2B lands. Everything downstream reads the claim's
    `is_authoritative` and `caveats` rather than checking which source it is,
    so nothing else has to move.
    """
    return PurchaseRegisterSource()
