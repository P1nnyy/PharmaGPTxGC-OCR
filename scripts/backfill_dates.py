"""Normalises invoice dates and batch expiries already stored in the graph.

Rows written before date normalisation hold whatever the supplier printed
(`03/08/2026`, `08/26`). Period filters compare ISO strings, so those rows match
no reporting period at all and silently vanish from every report.

Runs read-only by default. Inspect the plan, then re-run with --apply.

    python scripts/backfill_dates.py
    python scripts/backfill_dates.py --apply
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dates import normalize_expiry, normalize_invoice_date  # noqa: E402
from db.repositories import maintenance_repository  # noqa: E402


def plan_invoice_dates() -> tuple[list[dict], list[dict]]:
    """Splits stored dates into those needing a rewrite and those unparseable."""
    changes, unreadable = [], []
    for row in maintenance_repository.stored_invoice_dates():
        raw = row["invoice_date"]
        iso = normalize_invoice_date(raw)
        if iso is None:
            unreadable.append(row)
        elif iso != raw:
            changes.append({"invoice_id": row["invoice_id"], "invoice_date": iso, "was": raw})
    return changes, unreadable


def plan_expiries() -> tuple[list[dict], list[dict], list[dict]]:
    line_changes, batch_changes, unreadable = [], [], []
    for row in maintenance_repository.stored_expiries():
        line_raw, batch_raw = row.get("line_expiry"), row.get("batch_expiry")

        if line_raw:
            iso = normalize_expiry(line_raw)
            if iso is None:
                unreadable.append({"id": row["line_item_id"], "value": line_raw, "kind": "line"})
            elif iso != line_raw:
                line_changes.append({"line_item_id": row["line_item_id"], "expiry": iso})

        if batch_raw and row.get("batch_id"):
            iso = normalize_expiry(batch_raw)
            if iso is None:
                unreadable.append({"id": row["batch_id"], "value": batch_raw, "kind": "batch"})
            elif iso != batch_raw:
                batch_changes.append({"batch_id": row["batch_id"], "expiry": iso})

    return line_changes, batch_changes, unreadable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the changes. Omit for a dry run.")
    args = parser.parse_args()

    date_changes, date_unreadable = plan_invoice_dates()
    line_changes, batch_changes, expiry_unreadable = plan_expiries()

    print(f"Invoice dates to rewrite : {len(date_changes)}")
    for change in date_changes[:10]:
        print(f"  {change['was']!r} -> {change['invoice_date']}  ({change['invoice_id']})")
    if len(date_changes) > 10:
        print(f"  ... and {len(date_changes) - 10} more")

    print(f"Line-item expiries       : {len(line_changes)}")
    print(f"Batch expiries           : {len(batch_changes)}")

    # These are the rows a rewrite cannot save. They stay as they are and show
    # up in the data-quality report, which is the right place to fix them by
    # hand — guessing at an unreadable date would be worse than leaving it.
    if date_unreadable:
        print(f"\nUnreadable invoice dates ({len(date_unreadable)}) — left untouched:")
        for row in date_unreadable[:10]:
            print(f"  {row['invoice_date']!r}  ({row['invoice_id']})")
    if expiry_unreadable:
        print(f"\nUnreadable expiries ({len(expiry_unreadable)}) — left untouched:")
        for row in expiry_unreadable[:10]:
            print(f"  {row['value']!r}  ({row['kind']} {row['id']})")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write these changes.")
        return 0

    updated = maintenance_repository.apply_invoice_dates(
        [{"invoice_id": c["invoice_id"], "invoice_date": c["invoice_date"]} for c in date_changes]
    )
    touched = maintenance_repository.apply_expiries(line_changes, batch_changes)
    print(
        f"\nApplied: {updated} invoice dates, "
        f"{touched['line_items']} line-item expiries, {touched['batches']} batch expiries."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
