"""Mapping a photographed counter bill into the Sale schema.

The shop photographs a bill its own software printed — Marg, another POS, or a
handwritten book — and the same extraction stack that reads purchase invoices
reads it. Only the mapping differs, which is why the normalizer takes a
document role rather than being forked.

**The one thing a retail bill does not say out loud.** Whether the amount in
the line's Amount column already contains the tax. A pharmacy billing at MRP
prints an inclusive figure; a shop billing net-plus-tax prints an exclusive
one, and the two look identical on the page. Assuming either would misstate the
taxable value on every bill printed the other way.

So it is not assumed. Both readings are computed and each is tested against the
totals the bill itself printed in its footer; the reading that reconciles is
the reading the bill used. When neither reconciles — or the bill printed no
footer to test against — the basis is left UNRESOLVED, the discrepancy is
recorded, and the record stays a draft for a person to settle. That is the
whole reason this path lands in DRAFT rather than going straight to the return.
"""

from datetime import date
from typing import Any, Optional

from core.dates import normalize_invoice_date
from core.money import halve_tax, parse_rupees_to_paise, round_to_rupee, split_inclusive, tax_on_exclusive
from core.tax_periods import PeriodError, period_of


class PricingBasis:
    INCLUSIVE = "inclusive"
    EXCLUSIVE = "exclusive"
    UNRESOLVED = "unresolved"


class SaleMappingError(ValueError):
    """Raised when an extracted document cannot be mapped to a sale at all."""


def _paise(value: Any) -> Optional[int]:
    return parse_rupees_to_paise(value)


def _rate_bp(gst_percent: Any) -> Optional[int]:
    """A printed GST percentage as integer basis points."""
    if gst_percent is None:
        return None
    try:
        return int(round(float(gst_percent) * 100))
    except (TypeError, ValueError):
        return None


def _blocks_for_basis(lines: "list[tuple[int, int]]", basis: str) -> "list[dict]":
    """Rate blocks under one reading of what the line amounts mean."""
    grouped: dict[int, int] = {}
    for rate_bp, amount in lines:
        grouped[rate_bp] = grouped.get(rate_bp, 0) + amount

    blocks = []
    for rate_bp in sorted(grouped):
        amount = grouped[rate_bp]
        if basis == PricingBasis.INCLUSIVE:
            taxable, tax = split_inclusive(amount, rate_bp)
            gross = amount
        else:
            taxable = amount
            tax = tax_on_exclusive(amount, rate_bp)
            gross = amount + tax
        cgst, sgst = halve_tax(tax)
        blocks.append(
            {
                "rate_bp": rate_bp,
                "gross_paise": gross,
                "taxable_paise": taxable,
                "cgst_paise": cgst,
                "sgst_paise": sgst,
            }
        )
    return blocks


def _difference_report(blocks: "list[dict]", printed: dict) -> "list[str]":
    """Where a reading disagrees with what the bill printed."""
    taxable = sum(b["taxable_paise"] for b in blocks)
    cgst = sum(b["cgst_paise"] for b in blocks)
    sgst = sum(b["sgst_paise"] for b in blocks)

    differences = []
    if printed.get("subtotal") is not None and printed["subtotal"] != taxable:
        differences.append(
            f"Taxable value: lines add to {taxable / 100:.2f}, the bill prints "
            f"{printed['subtotal'] / 100:.2f}."
        )
    if printed.get("cgst") is not None and printed["cgst"] != cgst:
        differences.append(
            f"CGST: lines add to {cgst / 100:.2f}, the bill prints {printed['cgst'] / 100:.2f}."
        )
    if printed.get("sgst") is not None and printed["sgst"] != sgst:
        differences.append(
            f"SGST: lines add to {sgst / 100:.2f}, the bill prints {printed['sgst'] / 100:.2f}."
        )

    # The printed grand total is checked too, and separately from the parts.
    # A bill whose taxable value and tax both agree but whose total does not is
    # not a bill that reconciles — it is one with an arithmetic error on it, or
    # a line the reader missed, and either way a person needs to look.
    if printed.get("grand_total") is not None:
        gross = sum(b["gross_paise"] for b in blocks)
        rounded, _ = round_to_rupee(gross)
        # Any of three readings is acceptable: the bare sum, the sum rounded to
        # a rupee, or the sum plus whatever round-off the bill printed itself.
        acceptable = {gross, rounded}
        if printed.get("roundoff") is not None:
            acceptable.add(gross + printed["roundoff"])
        if printed["grand_total"] not in acceptable:
            differences.append(
                f"Total: lines add to {gross / 100:.2f}, the bill prints "
                f"{printed['grand_total'] / 100:.2f}."
            )

    return differences


def map_sale_from_extraction(canonical: Any, today: Optional[date] = None) -> dict:
    """Maps an extracted bill to the fields a Sale stores.

    Pure: no database, no clock except `today`. Returns a draft's worth of
    figures plus a reconciliation report; it never decides that a disagreement
    is close enough.
    """
    document = canonical if isinstance(canonical, dict) else canonical.model_dump()

    sale_date = normalize_invoice_date(document.get("invoice_date"))
    if not sale_date:
        raise SaleMappingError(
            "The bill has no readable date, so it cannot be filed into a period."
        )
    try:
        tax_period = period_of(sale_date)
    except PeriodError as exc:
        raise SaleMappingError(str(exc)) from exc

    lines: list[tuple[int, int]] = []
    unpriced = 0
    for item in document.get("line_items") or []:
        entry = item if isinstance(item, dict) else item.model_dump()
        rate_bp = _rate_bp(entry.get("gst_percent"))
        amount = _paise(entry.get("amount"))
        if rate_bp is None or amount is None:
            unpriced += 1
            continue
        lines.append((rate_bp, amount))

    printed = {
        "subtotal": _paise(document.get("subtotal")),
        "cgst": _paise(document.get("cgst")),
        "sgst": _paise(document.get("sgst")),
        "grand_total": _paise(document.get("grand_total")),
        "roundoff": _paise(document.get("roundoff")),
    }

    if not lines and printed["grand_total"] is None:
        raise SaleMappingError(
            "The bill has neither readable lines nor a printed total — there is "
            "nothing to record."
        )

    # Which reading did this bill use? Let its own footer answer.
    has_footer = any(printed[k] is not None for k in ("subtotal", "cgst", "sgst"))
    candidates = {
        PricingBasis.INCLUSIVE: _blocks_for_basis(lines, PricingBasis.INCLUSIVE),
        PricingBasis.EXCLUSIVE: _blocks_for_basis(lines, PricingBasis.EXCLUSIVE),
    }
    differences_by_basis = {
        basis: _difference_report(blocks, printed) for basis, blocks in candidates.items()
    }

    basis = PricingBasis.UNRESOLVED
    if has_footer and lines:
        for candidate in (PricingBasis.INCLUSIVE, PricingBasis.EXCLUSIVE):
            if not differences_by_basis[candidate]:
                basis = candidate
                break

    if basis == PricingBasis.UNRESOLVED:
        # Nothing reconciled. The inclusive reading is shown so the reviewer
        # has figures to correct rather than an empty form — and every figure
        # is marked unresolved so none of it can be mistaken for confirmed.
        blocks = candidates[PricingBasis.INCLUSIVE]
        differences = (
            differences_by_basis[PricingBasis.INCLUSIVE]
            if has_footer
            else ["The bill prints no taxable or tax total to check the lines against."]
        )
    else:
        blocks = candidates[basis]
        differences = []

    taxable = sum(b["taxable_paise"] for b in blocks)
    cgst = sum(b["cgst_paise"] for b in blocks)
    sgst = sum(b["sgst_paise"] for b in blocks)
    before_rounding = sum(b["gross_paise"] for b in blocks)
    grand_total, round_off = round_to_rupee(before_rounding)

    review_notes = []
    if unpriced:
        review_notes.append(
            f"{unpriced} line{'s' if unpriced != 1 else ''} had no readable amount or "
            "GST rate and are not in these totals."
        )
    if any(b["rate_bp"] == 0 for b in blocks):
        # Exempt, nil-rated and non-GST all print as no tax, so the bill
        # cannot distinguish them. Guessing would mis-state GSTR-1 Table 8.
        review_notes.append(
            "This bill has lines at 0%. Whether they are exempt, nil-rated or "
            "non-GST cannot be read off the bill — classify them before confirming."
        )
    if basis == PricingBasis.UNRESOLVED:
        review_notes.append(
            "Could not tell whether the line amounts include GST. The figures "
            "below read them as inclusive — check them against the bill."
        )

    return {
        "sale_date": sale_date,
        "tax_period": tax_period,
        "bill_number": (document.get("invoice_number") or "").strip() or None,
        "rate_blocks": blocks,
        "taxable_paise": taxable,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        # A bill cannot tell these three apart, so they start at zero and the
        # reviewer moves value into them. See the note above.
        "exempt_paise": 0,
        "nil_rated_paise": 0,
        "non_gst_paise": 0,
        "round_off_paise": round_off,
        "grand_total_paise": grand_total,
        # A photographed bill records what was sold, not how it was paid for.
        "payments": [],
        "rate_source": "extracted",
        "is_aggregate": False,
        "pricing_basis": basis,
        "printed_totals": printed,
        "reconciliation": {
            "reconciles": basis != PricingBasis.UNRESOLVED and not differences,
            "differences": differences,
        },
        "review_notes": review_notes,
    }


def find_existing_by_image(content_hash_hex: str) -> Optional[dict]:
    """A sale already produced by this exact image, if there is one.

    Checked *before* extraction, not after. Extraction is billable, and the
    whole point of being idempotent on the image is that re-uploading the same
    photograph costs nothing — a check that ran afterwards would still pay
    Azure for a document we already hold.
    """
    from core.tenancy import current_tenant
    from db.repositories import sales_repository

    matches = sales_repository.find_by_source_file_hash(content_hash_hex, current_tenant())
    return matches[0] if matches else None


def record_sale_from_image(
    canonical: Any,
    content_hash_hex: str,
    source_image_ref: Optional[str] = None,
    created_by: Optional[str] = None,
    today: Optional[date] = None,
) -> "tuple[dict, bool, dict]":
    """Stores an extracted bill as a draft sale. Returns `(sale, created, mapping)`.

    Idempotent on the image's content hash together with the bill number the
    reader found on it. The image alone is not the key: the same bill
    photographed twice is two images of one document, and the bill number is
    what says so.

    Lands as DRAFT without exception. A machine read these figures off a
    photograph, and the house rules do not let a machine's reading reach a
    return — a person confirms it first, which is also when the exempt /
    nil-rated split and any unreconciled difference get settled.
    """
    from core.idempotency import dedupe_key
    from core.tenancy import current_tenant
    from db.repositories import sales_repository
    from models.sales import CaptureMode, DocumentClass, SaleStatus

    mapping = map_sale_from_extraction(canonical, today=today)

    key = dedupe_key(
        current_tenant(),
        CaptureMode.BILL_PHOTO,
        content_hash_hex,
        mapping["bill_number"],
    )

    sale, created = sales_repository.upsert_sale(
        dedupe_key=key,
        computed=mapping,
        capture_mode=CaptureMode.BILL_PHOTO,
        document_class=DocumentClass.INVOICE_CUM_BILL_OF_SUPPLY,
        status=SaleStatus.DRAFT,
        created_by=created_by,
        bill_number=mapping["bill_number"],
        source_file_hash=content_hash_hex,
        source_image_ref=source_image_ref,
        source_format="image",
    )
    return sale, created, mapping
