"""Merges the separately-extracted pages of a multi-page invoice into one
CanonicalInvoice, and checks that the pages actually belong together.

Why totals are not summed
-------------------------
On a real two-page pharma invoice (Arora Bros, bill GST-15168) the page
carrying the totals block prints the figures for the WHOLE order, not for its
own page: page 1's eleven items sum to 1753.00, page 2's five sum to 524.50,
and page 2's printed TOTAL is 2277.50 - the sum of both. Adding per-page
subtotals together would therefore double-count.

Some distributors also print a running "carried forward" subtotal on every
page, which would double-count even more aggressively.

So totals are taken as a COMPLETE BLOCK from a single page - the one carrying
the final payable figure - rather than being combined field by field across
pages. Mixing (say) page 1's subtotal with page 2's grand total would produce
an internally inconsistent set that fails the review screen's math check.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from rapidfuzz import fuzz

from extraction.normalizers.canonical_invoice import CanonicalInvoice
from extraction.normalizers.azure_invoice_normalizer import ocr_visual_key
from extraction.normalizers.amount_inference import fill_missing_amounts

# Identity fields carried from the first page that supplies them.
_HEADER_FIELDS = (
    "invoice_number",
    "invoice_date",
    "seller_name",
    "buyer_name",
    "seller_gstin",
    "buyer_gstin",
    "seller_address",
    "buyer_address",
    "seller_phone",
    "drug_license",
)

# Financial fields that must move together, as one internally consistent set.
_TOTALS_FIELDS = ("subtotal", "discount", "cgst", "sgst", "igst", "grand_total", "roundoff")

# Fields compared to decide whether pages belong to the same invoice. A
# mismatch on invoice_number or seller_gstin is treated as hard evidence the
# pages are different documents; the rest are advisory.
_HARD_IDENTITY_FIELDS = ("invoice_number", "seller_gstin")
_SOFT_IDENTITY_FIELDS = ("invoice_date", "buyer_gstin", "seller_name")

# Descriptive names are compared fuzzily, structured identifiers are not.
#
# A continuation page often catches only part of the seller name, or picks it
# up from a diagonal watermark - a real page 2 read as "GURKIE" against page
# 1's "GURKIRAT MEDICOS" is the same company, not a different invoice, and
# flagging it trains the user to dismiss the dialog.
#
# Identifiers stay exact deliberately: "A002571" and "A002572" are two
# consecutive invoices from the same supplier and score 93 on partial ratio,
# so fuzzy-matching them is exactly how two different invoices would get
# welded into one.
_FUZZY_NAME_FIELDS = frozenset({"seller_name"})
_NAME_SIMILARITY_THRESHOLD = 85.0


class PageConflict(BaseModel):
    field: str
    severity: str  # "hard" | "soft"
    values: Dict[int, Any]  # 1-based page number -> value seen on that page
    message: str


class ConsistencyReport(BaseModel):
    is_consistent: bool
    page_count: int
    conflicts: List[PageConflict] = []
    warnings: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


def _normalized(value: Any) -> Optional[str]:
    """Case/whitespace-insensitive form for comparing identity fields. OCR
    routinely varies capitalisation and spacing between pages of the same
    document, and those differences are not evidence of different invoices."""
    if value is None:
        return None
    text = " ".join(str(value).split()).strip().upper()
    return text or None


def _values_disagree(field: str, values: List[Any]) -> bool:
    """Whether the values seen for a field across pages actually conflict.

    Name fields tolerate partial OCR (see _FUZZY_NAME_FIELDS); everything else
    must match exactly once normalized for case and whitespace.
    """
    normalized = [_normalized(v) for v in values]
    normalized = [v for v in normalized if v]
    if len(normalized) < 2:
        return False

    if field not in _FUZZY_NAME_FIELDS:
        # Identifiers compare exactly, but only after collapsing characters
        # that OCR genuinely confuses. A real case: the same GSTIN read as
        # ...F1ZN on one page and ...FIZN on the other - one document, two
        # readings of the same glyph.
        #
        # This stays safe for sequential identifiers because each look-alike
        # group holds at most one digit, so two numerically different values
        # can never collapse together: A002571 and A002572 remain distinct.
        return len({ocr_visual_key(v) for v in normalized}) > 1

    # Every pair must be plausibly the same name for the field to agree.
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            if fuzz.partial_ratio(normalized[i], normalized[j]) < _NAME_SIMILARITY_THRESHOLD:
                return True
    return False


def check_pages_consistent(pages: List[CanonicalInvoice]) -> ConsistencyReport:
    """Compares identity fields across pages to test the user's assertion that
    they form a single order.

    Only pages that actually carry a given field take part in that field's
    comparison - a continuation page legitimately omits most header fields,
    and absence is not disagreement.
    """
    if len(pages) < 2:
        return ConsistencyReport(is_consistent=True, page_count=len(pages))

    conflicts: List[PageConflict] = []
    warnings: List[str] = []

    for field in _HARD_IDENTITY_FIELDS + _SOFT_IDENTITY_FIELDS:
        seen: Dict[int, Any] = {}
        for idx, page in enumerate(pages, start=1):
            value = _normalized(getattr(page, field, None))
            if value is not None:
                seen[idx] = getattr(page, field)

        if _values_disagree(field, list(seen.values())):
            hard = field in _HARD_IDENTITY_FIELDS
            conflicts.append(
                PageConflict(
                    field=field,
                    severity="hard" if hard else "soft",
                    values=seen,
                    message=(
                        f"Pages disagree on {field.replace('_', ' ')}: "
                        + ", ".join(f"page {p} = {v!r}" for p, v in seen.items())
                    ),
                )
            )

    if not any(_normalized(getattr(p, "invoice_number", None)) for p in pages):
        warnings.append(
            "No invoice number was read on any page, so the pages could not be "
            "automatically confirmed as one order."
        )

    pages_with_totals = [i for i, p in enumerate(pages, start=1) if p.grand_total is not None]
    if len(pages_with_totals) > 1:
        warnings.append(
            f"More than one page carries a final total (pages {pages_with_totals}). "
            "The last one was used; check the totals on the review screen."
        )
    elif not pages_with_totals:
        warnings.append(
            "No page carried a final total, so the invoice total was derived from "
            "the line items."
        )

    return ConsistencyReport(
        is_consistent=not any(c.severity == "hard" for c in conflicts),
        page_count=len(pages),
        conflicts=conflicts,
        warnings=warnings,
    )


def _select_totals_page(pages: List[CanonicalInvoice]) -> Optional[CanonicalInvoice]:
    """Picks the single page whose totals block describes the whole invoice.

    Preference is the LAST page carrying a grand total: on a multi-page
    invoice the payable figure is printed once, on the final page, and any
    earlier page showing totals is a running carry-forward that does not
    describe the full order.
    """
    for page in reversed(pages):
        if page.grand_total is not None:
            return page
    for page in reversed(pages):
        if page.subtotal is not None:
            return page
    return None


def merge_invoice_pages(pages: List[CanonicalInvoice]) -> CanonicalInvoice:
    """Combines per-page extractions into a single invoice.

    Pages must already be in reading order; ordering is the caller's concern
    since only the user knows which photo is page 1.
    """
    if not pages:
        raise ValueError("merge_invoice_pages requires at least one page.")
    if len(pages) == 1:
        return pages[0]

    merged = CanonicalInvoice()

    # Identity: first page that supplies each field wins. Continuation pages
    # often repeat the header, and where they do it should agree - any
    # disagreement is surfaced separately by check_pages_consistent.
    for field in _HEADER_FIELDS:
        for page in pages:
            value = getattr(page, field, None)
            if value is not None and str(value).strip() != "":
                setattr(merged, field, value)
                break

    # Line items concatenate in page order, which defines their final ordering.
    line_items = []
    for page in pages:
        line_items.extend(page.line_items)
    merged.line_items = line_items

    # Totals move as one block from a single page - see module docstring.
    totals_page = _select_totals_page(pages)
    if totals_page is not None:
        for field in _TOTALS_FIELDS:
            setattr(merged, field, getattr(totals_page, field, None))

    # Fall back to the line items only when no page stated a subtotal at all,
    # mirroring the single-page normalizer's behaviour.
    if merged.subtotal is None:
        amounts = [item.amount for item in line_items if isinstance(item.amount, (int, float))]
        if amounts:
            merged.subtotal = round(sum(amounts), 2)

    # Re-run amount derivation across the combined set. A continuation page
    # often carries too few rows to infer a formula on its own, but the full
    # invoice does - so a page-2 line whose Amount was unreadable can be
    # derived from the pattern page 1 demonstrates.
    amount_fill = fill_missing_amounts(line_items)

    merged.extraction_engine = next(
        (p.extraction_engine for p in pages if p.extraction_engine), None
    )
    # The weakest page bounds confidence in the merged result: one badly-read
    # page compromises the whole invoice.
    confidences = [p.confidence for p in pages if p.confidence is not None]
    merged.confidence = min(confidences) if confidences else None
    merged.page_angle = next((p.page_angle for p in pages if p.page_angle is not None), None)
    # Per-page angles, so the viewer can orient each sheet on its own terms.
    merged.page_angles = [
        (p.page_angle if p.page_angle is not None else 0.0) for p in pages
    ]

    merged.raw_engine_metadata = {
        "multipage": True,
        "page_count": len(pages),
        "totals_source_page": (pages.index(totals_page) + 1) if totals_page is not None else None,
        "line_items_per_page": [len(p.line_items) for p in pages],
        "amount_formula": amount_fill["formula"],
        "estimated_amount_count": amount_fill["filled"],
        "pages": [p.raw_engine_metadata for p in pages],
    }

    return merged
