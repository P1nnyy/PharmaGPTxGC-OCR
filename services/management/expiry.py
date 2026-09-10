"""Expiry risk, and the input credit that goes with it.

The report this product is for.

A pharmacy's expiry loss is not one number, it is two. The stock is worth what
it cost, and on top of that the input credit already claimed on it has to be
**reversed permanently** under Section 17(5)(h) when the goods are written off -
"goods lost, stolen, destroyed or written off" - because credit is only for
inputs used in making taxable supplies, and stock that expired on the shelf
never made one. So a ₹18,400 write-off is really ₹18,400 plus ₹2,208 of credit
going back, and the second figure is the one nobody sees coming.

And it is avoidable. Most distributors accept saleable returns up to some
window before expiry. Inside that window the answer is "send it back this
week"; outside it the answer is "this is a loss, and here is what it will cost
you in March". Which of those a shopkeeper is looking at depends entirely on a
per-vendor number that is on no invoice - so where it is unknown, this says so
rather than guessing, because a guess that says "you have time" when you do not
is worse than silence.

Buckets are 30/60/90/180 days and are **cumulative-exclusive**: a batch
expiring in 45 days appears in the 60 bucket and not in the 30. Overlapping
buckets would make the totals unaddable, and adding them is the first thing
anyone does.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from core.dates import normalize_expiry

# The windows the report reckons in. Ordered, and each bucket holds what falls
# after the previous boundary and on or before its own.
BUCKETS = (30, 60, 90, 180)

# Batches already past expiry. Not a bucket - there is no time left to act in,
# and mixing them into "30 days" would suggest there is.
EXPIRED = "EXPIRED"


def _as_date(value: Optional[str]) -> Optional[date]:
    """Reads a stored expiry, tolerating rows that predate normalising."""
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    normalized = normalize_expiry(text)
    if not normalized:
        return None
    try:
        return date.fromisoformat(str(normalized)[:10])
    except ValueError:
        return None


@dataclass
class ExpiringBatch:
    product_id: str
    product_name: Optional[str]
    batch_number: str
    expiry: str
    days_left: int
    quantity: float
    value_at_mrp_paise: int
    value_at_cost_paise: int
    input_tax_at_risk_paise: int
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    return_window_days: Optional[int] = None
    bucket: str = ""

    @property
    def days_left_to_return(self) -> Optional[int]:
        """How long until the distributor stops taking this back.

        None when the window is unknown - which is a different thing from zero
        and is presented differently.
        """
        if self.return_window_days is None:
            return None
        return self.days_left - self.return_window_days

    @property
    def can_still_be_returned(self) -> Optional[bool]:
        remaining = self.days_left_to_return
        return None if remaining is None else remaining > 0

    def to_dict(self) -> dict:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "batch_number": self.batch_number,
            "expiry": self.expiry,
            "days_left": self.days_left,
            "bucket": self.bucket,
            "quantity": float(self.quantity),
            "value_at_mrp": round(self.value_at_mrp_paise / 100, 2),
            "value_at_cost": round(self.value_at_cost_paise / 100, 2),
            "input_tax_at_risk": round(self.input_tax_at_risk_paise / 100, 2),
            "vendor_id": self.vendor_id,
            "vendor_name": self.vendor_name,
            "return_window_days": self.return_window_days,
            "days_left_to_return": self.days_left_to_return,
            "can_still_be_returned": self.can_still_be_returned,
        }


@dataclass
class Bucket:
    label: str
    days: Optional[int]
    batches: list = field(default_factory=list)

    def _sum(self, attribute: str) -> int:
        return sum(getattr(b, attribute) for b in self.batches)

    def to_dict(self) -> dict:
        returnable = [b for b in self.batches if b.can_still_be_returned]
        unknown = [b for b in self.batches if b.can_still_be_returned is None]
        return {
            "label": self.label,
            "days": self.days,
            "batch_count": len(self.batches),
            "quantity": round(sum(float(b.quantity) for b in self.batches), 3),
            "value_at_mrp": round(self._sum("value_at_mrp_paise") / 100, 2),
            "value_at_cost": round(self._sum("value_at_cost_paise") / 100, 2),
            "input_tax_at_risk": round(self._sum("input_tax_at_risk_paise") / 100, 2),
            # Split out because it is the difference between a task and a loss.
            "still_returnable_value_at_cost": round(
                sum(b.value_at_cost_paise for b in returnable) / 100, 2
            ),
            "return_window_unknown_count": len(unknown),
            "rows": [b.to_dict() for b in self.batches],
        }


def build(
    costing,
    today: date,
    vendor_windows: Optional[dict] = None,
    vendor_names: Optional[dict] = None,
    horizon_days: int = 180,
) -> dict:
    """Everything expiring inside the horizon, bucketed, with the tax at risk.

    Batches with nothing left on hand are excluded: stock that has been sold
    carries no expiry risk, and listing it would bury the rows that matter
    under the ones already dealt with.
    """
    vendor_windows = vendor_windows or {}
    vendor_names = vendor_names or {}

    buckets = {days: Bucket(label=f"{days} days", days=days) for days in BUCKETS}
    expired = Bucket(label="Already expired", days=None)

    for position in costing.by_batch.values():
        on_hand = position.on_hand
        if on_hand <= 0:
            continue
        expiry_date = _as_date(position.expiry)
        if expiry_date is None:
            continue

        days_left = (expiry_date - today).days
        if days_left > horizon_days:
            continue

        batch = ExpiringBatch(
            product_id=position.product_id,
            product_name=position.product_name,
            batch_number=position.batch_number,
            expiry=expiry_date.isoformat(),
            days_left=days_left,
            quantity=float(on_hand),
            value_at_mrp_paise=position.mrp_value_of(on_hand),
            value_at_cost_paise=position.cost_of(on_hand),
            input_tax_at_risk_paise=position.input_tax_of(on_hand),
            vendor_id=position.vendor_id,
            vendor_name=vendor_names.get(position.vendor_id),
            return_window_days=vendor_windows.get(position.vendor_id),
        )

        if days_left < 0:
            batch.bucket = EXPIRED
            expired.batches.append(batch)
            continue

        for days in BUCKETS:
            if days_left <= days:
                batch.bucket = f"{days}"
                buckets[days].batches.append(batch)
                break

    for bucket in list(buckets.values()) + [expired]:
        # Soonest first: the row at the top is the one to act on today.
        bucket.batches.sort(key=lambda b: (b.days_left, -b.value_at_cost_paise))

    every = [b for bucket in buckets.values() for b in bucket.batches] + expired.batches
    total_tax = sum(b.input_tax_at_risk_paise for b in every)
    total_cost = sum(b.value_at_cost_paise for b in every)
    returnable = [b for b in every if b.can_still_be_returned]
    unknown_window = [b for b in every if b.can_still_be_returned is None]

    return {
        "as_of": today.isoformat(),
        "horizon_days": horizon_days,
        "buckets": [buckets[days].to_dict() for days in BUCKETS],
        "expired": expired.to_dict(),
        "totals": {
            "batch_count": len(every),
            "value_at_cost": round(total_cost / 100, 2),
            "value_at_mrp": round(sum(b.value_at_mrp_paise for b in every) / 100, 2),
            # The headline. This is what has to go back to the department if
            # the stock is destroyed rather than returned.
            "input_tax_at_risk": round(total_tax / 100, 2),
            "input_tax_at_risk_paise": total_tax,
            "still_returnable_value_at_cost": round(
                sum(b.value_at_cost_paise for b in returnable) / 100, 2
            ),
            "still_returnable_batch_count": len(returnable),
            "return_window_unknown_count": len(unknown_window),
        },
        "statutory_note": (
            "Input credit on stock that is written off must be reversed permanently "
            "under Section 17(5)(h) and reported in GSTR-3B table 4(B)(1). It cannot "
            "be reclaimed. Sending stock back to the distributor instead avoids the "
            "reversal entirely."
        ),
        "return_window_note": (
            f"{len(unknown_window)} of these batches come from distributors whose "
            "return window nobody has recorded. Until it is, this report cannot say "
            "whether they can still go back — and it will not guess."
        ) if unknown_window else None,
    }
