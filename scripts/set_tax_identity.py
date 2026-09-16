"""Declares a shop's HSN digit policy and filing frequency.

Both are declarations, not derivations. Aggregate turnover is PAN-wide across
every GSTIN on the PAN and this workspace holds the sales of one of them, so
the shop has to say. Until it does, the engine defaults: six HSN digits, which
over-reports for a shop under Rs 5 crore, and no filing frequency at all,
which blocks a period from closing.

Runs read-only by default. Inspect the plan, then re-run with --apply.

    python scripts/set_tax_identity.py
    python scripts/set_tax_identity.py --apply --hsn-policy FOUR_DIGIT

Writes to whatever NEO4J_URI points at, which for this project is production.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.graph_db import get_driver  # noqa: E402

POLICIES = ("FOUR_DIGIT", "SIX_DIGIT")
FREQUENCIES = ("MONTHLY", "QUARTERLY")


def shops() -> list:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(
            lambda tx: [
                dict(r["ph"])
                for r in tx.run(
                    "MATCH (ph:Pharmacy) RETURN ph ORDER BY ph.legal_name, ph.id"
                )
            ]
        )


def apply(pharmacy_id: str, fields: dict) -> dict:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(
            lambda tx: dict(
                tx.run(
                    "MATCH (ph:Pharmacy {id: $id}) SET ph += $fields RETURN ph",
                    id=pharmacy_id,
                    fields=fields,
                ).single()["ph"]
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the change")
    parser.add_argument("--pharmacy-id", help="one shop; default is every shop")
    parser.add_argument("--hsn-policy", choices=POLICIES)
    parser.add_argument("--filing-frequency", choices=FREQUENCIES)
    args = parser.parse_args()

    fields = {}
    if args.hsn_policy:
        fields["hsn_digit_policy"] = args.hsn_policy
    if args.filing_frequency:
        fields["filing_frequency"] = args.filing_frequency

    targets = [
        shop
        for shop in shops()
        if not args.pharmacy_id or shop.get("id") == args.pharmacy_id
    ]
    if not targets:
        print("no matching shop")
        return 1

    for shop in targets:
        print(f"\n{shop.get('legal_name') or shop.get('name') or '(unnamed)'}")
        print(f"  id                 {shop.get('id')}")
        print(f"  gstin              {shop.get('gstin')}")
        print(f"  hsn_digit_policy   {shop.get('hsn_digit_policy') or '(unset -> six digits)'}")
        print(f"  filing_frequency   {shop.get('filing_frequency') or '(unset -> blocks closing)'}")
        print(f"  aato_paise         {shop.get('aato_paise')}")
        for key, value in fields.items():
            print(f"  would set {key} = {value}")

    if not fields:
        print("\nnothing to set. Pass --hsn-policy and/or --filing-frequency.")
        return 0
    if not args.apply:
        print(f"\nread-only. Re-run with --apply to write to {len(targets)} shop(s).")
        return 0

    for shop in targets:
        updated = apply(shop["id"], fields)
        print(
            f"\nwrote {shop['id']}: "
            + ", ".join(f"{k}={updated.get(k)}" for k in fields)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
