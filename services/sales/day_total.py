"""Day-total entry: the aggregate a shop declares instead of billing through us.

The adoption ramp's first rung. A pharmacy that bills on Marg, on another POS,
or in a handwritten book can still file through PharmaFlow by declaring, once a
day, what it took at each GST slab. That is legally sufficient to build the
B2CS table of GSTR-1, which is reported per place of supply and rate rather
than per invoice.

What this deliberately is not: it carries no lines, no batches and no stock
movements, so nothing downstream may infer margin, stock depletion or
item-level demand from it. The `capture_mode` on the resulting Sale is what
lets reporting say so out loud instead of quietly averaging an aggregate in
beside document-level data.

**The figures the shop enters are tax-inclusive** — what the till collected at
that slab — and the taxable value is derived from them. That direction was a
deliberate decision, not a default: it is the number a day book and a POS
Z-report actually show, and it makes the per-slab figures add up against the
payment split without staff doing arithmetic of their own.
"""

from datetime import date
from typing import Any, Optional

from core.money import BP_DENOMINATOR, halve_tax, round_to_rupee, split_inclusive
from core.tax_periods import PeriodError, period_of
from core.dates import normalize_invoice_date

# The methods a counter actually takes money by. An unknown method is refused
# rather than stored: the payment split reconciles the day's cash drawer, and a
# free-text method makes that reconciliation unauditable.
PAYMENT_METHODS = {"cash", "upi", "card", "credit"}

# 100%. Above this is certainly a typo — most likely a rate typed in basis
# points when the field wanted percent, or the other way round.
MAX_RATE_BP = BP_DENOMINATOR


class DayTotalError(ValueError):
    """Raised when a day total cannot be accepted. Message is user-facing."""


def _amount(value: Any, label: str) -> int:
    """Reads an amount that must already be integer paise."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise DayTotalError(f"{label} must be a whole number of paise.")
    if value < 0:
        raise DayTotalError(f"{label} cannot be negative.")
    return value


def compute_day_total(
    sale_date: str,
    rate_blocks: "list[dict]",
    exempt_paise: int,
    nil_rated_paise: int,
    non_gst_paise: int,
    payments: "list[dict]",
    today: Optional[date] = None,
) -> dict:
    """Turns a declared day into the figures a Sale stores.

    Pure: no clock read except `today`, which callers pass so tests are not
    time-dependent, and no database access. Raises `DayTotalError` with a
    message meant to be shown to the person who typed the figures.
    """
    iso = normalize_invoice_date(sale_date)
    if not iso:
        raise DayTotalError(f"Could not read {sale_date!r} as a date.")
    if iso > (today or date.today()).isoformat():
        raise DayTotalError("That date is in the future — a day cannot be totalled before it ends.")

    try:
        tax_period = period_of(iso)
    except PeriodError as exc:
        raise DayTotalError(str(exc)) from exc

    exempt = _amount(exempt_paise, "Exempt total")
    nil_rated = _amount(nil_rated_paise, "Nil-rated total")
    non_gst = _amount(non_gst_paise, "Non-GST total")

    computed_blocks = []
    seen_rates: set[int] = set()
    for entry in rate_blocks:
        rate_bp = entry.get("rate_bp")
        if isinstance(rate_bp, bool) or not isinstance(rate_bp, int):
            raise DayTotalError("Each slab needs a rate in basis points (1200 for 12%).")
        if rate_bp < 0 or rate_bp > MAX_RATE_BP:
            raise DayTotalError(
                f"{rate_bp / 100:g}% is not a usable GST rate. Rates run from 0% to 100%."
            )
        if rate_bp in seen_rates:
            raise DayTotalError(
                f"The {rate_bp / 100:g}% slab is entered twice. State each slab once, "
                "with the day's whole total for it."
            )
        seen_rates.add(rate_bp)

        gross = _amount(entry.get("gross_paise"), f"The {rate_bp / 100:g}% total")
        taxable, tax = split_inclusive(gross, rate_bp)
        cgst, sgst = halve_tax(tax)
        computed_blocks.append(
            {
                "rate_bp": rate_bp,
                "gross_paise": gross,
                "taxable_paise": taxable,
                "cgst_paise": cgst,
                "sgst_paise": sgst,
            }
        )

    computed_blocks.sort(key=lambda b: b["rate_bp"])

    taxable_total = sum(b["taxable_paise"] for b in computed_blocks)
    cgst_total = sum(b["cgst_paise"] for b in computed_blocks)
    sgst_total = sum(b["sgst_paise"] for b in computed_blocks)
    taxed_gross = sum(b["gross_paise"] for b in computed_blocks)
    untaxed = exempt + nil_rated + non_gst

    if taxed_gross == 0 and untaxed == 0:
        raise DayTotalError("There is nothing in this day — every total is zero.")

    # The reconciliation the house rules require: the per-slab figures are a
    # decomposition of what was collected, so they must add back to it exactly.
    # `split_inclusive` derives the tax by subtraction so this holds by
    # construction — which is precisely why it is worth asserting. If it ever
    # fails, the arithmetic changed underneath and the figure is not to be
    # trusted.
    if taxable_total + cgst_total + sgst_total != taxed_gross:
        raise DayTotalError(
            "The slab figures do not reconcile to what was collected. "
            "This is a bug, not a data problem — nothing has been saved."
        )

    before_rounding = taxed_gross + untaxed
    grand_total, round_off = round_to_rupee(before_rounding)

    cleaned_payments = []
    for payment in payments:
        method = str(payment.get("method", "")).strip().lower()
        if method not in PAYMENT_METHODS:
            raise DayTotalError(
                f"{payment.get('method')!r} is not a payment method. "
                f"Use one of: {', '.join(sorted(PAYMENT_METHODS))}."
            )
        amount = _amount(payment.get("amount_paise"), f"The {method} amount")
        reference = payment.get("reference")
        cleaned_payments.append(
            {
                "method": method,
                "amount_paise": amount,
                "reference": str(reference).strip() if reference else None,
            }
        )

    paid = sum(p["amount_paise"] for p in cleaned_payments)
    if paid != grand_total:
        difference = grand_total - paid
        raise DayTotalError(
            "The payment split does not add up to the day's total: "
            f"{'short by' if difference > 0 else 'over by'} "
            f"{abs(difference) / 100:.2f}."
        )

    return {
        "sale_date": iso,
        "tax_period": tax_period,
        "rate_blocks": computed_blocks,
        "taxable_paise": taxable_total,
        "cgst_paise": cgst_total,
        "sgst_paise": sgst_total,
        "exempt_paise": exempt,
        "nil_rated_paise": nil_rated,
        "non_gst_paise": non_gst,
        "round_off_paise": round_off,
        "grand_total_paise": grand_total,
        "payments": cleaned_payments,
        # The slabs came from the operator, not from a rate table resolved
        # against the sale date. Reporting has to be able to say which, so the
        # provenance travels with the figures rather than being assumed.
        "rate_source": "declared",
        # No lines, by construction. Reporting reads this rather than
        # inferring it from the capture mode.
        "is_aggregate": True,
    }


def record_day_total(
    request: dict,
    created_by: Optional[str] = None,
    today: Optional[date] = None,
) -> "tuple[dict, bool]":
    """Computes a day total and stores it, once. Returns `(sale, created)`.

    Idempotent on (pharmacy, DAY_TOTAL, date): a shop has one day total per
    day, so re-posting the same date returns what is already stored rather than
    declaring the day's output tax a second time. It does not overwrite either
    — correcting a day that was already entered is a PATCH, which is a
    deliberate act rather than a retry.
    """
    # Imported here rather than at module import so the pure computation above
    # stays importable — and testable — without a database driver.
    from core.idempotency import dedupe_key
    from core.tenancy import current_tenant
    from db.repositories import sales_repository
    from models.sales import CaptureMode, DocumentClass, SaleStatus

    computed = compute_day_total(
        sale_date=request.get("sale_date"),
        rate_blocks=[dict(b) for b in request.get("rate_blocks") or []],
        exempt_paise=request.get("exempt_paise", 0),
        nil_rated_paise=request.get("nil_rated_paise", 0),
        non_gst_paise=request.get("non_gst_paise", 0),
        payments=[dict(p) for p in request.get("payments") or []],
        today=today,
    )

    key = dedupe_key(current_tenant(), CaptureMode.DAY_TOTAL, computed["sale_date"])

    return sales_repository.upsert_sale(
        dedupe_key=key,
        computed=computed,
        capture_mode=CaptureMode.DAY_TOTAL,
        # A day total stands for the counter bills the shop issued that day,
        # which for a pharmacy are Rule 46A documents covering taxable and
        # exempt supplies together.
        document_class=DocumentClass.INVOICE_CUM_BILL_OF_SUPPLY,
        # Typed by a person who was there. There is nothing further to confirm,
        # unlike an extracted or imported record.
        status=SaleStatus.CONFIRMED,
        created_by=created_by,
        notes=request.get("notes"),
    )


def recompute_day_total(
    sale_id: str,
    request: dict,
    updated_by: Optional[str] = None,
    today: Optional[date] = None,
) -> dict:
    """Corrects a day total that has already been entered.

    The repository refuses this once the period is filed, which is the whole
    point of the lock: up to filing a mistyped day is simply fixed; after it,
    the figures are part of a return and a correction is a new document.
    """
    from db.repositories import sales_repository

    computed = compute_day_total(
        sale_date=request.get("sale_date"),
        rate_blocks=[dict(b) for b in request.get("rate_blocks") or []],
        exempt_paise=request.get("exempt_paise", 0),
        nil_rated_paise=request.get("nil_rated_paise", 0),
        non_gst_paise=request.get("non_gst_paise", 0),
        payments=[dict(p) for p in request.get("payments") or []],
        today=today,
    )
    return sales_repository.update_sale(
        sale_id=sale_id,
        computed=computed,
        updated_by=updated_by,
        notes=request.get("notes"),
    )
