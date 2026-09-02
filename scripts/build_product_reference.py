"""Builds the local product reference index from the source CSV.

Run once, and again whenever a newer export of the reference data arrives:

    python scripts/build_product_reference.py ~/Downloads/indian_pharmaceutical_products_clean.csv

The index lands in datasets/product_reference.sqlite, which is gitignored -
it is a build artefact, and the 69MB CSV it comes from does not belong in the
repository either. Anything that reads it checks first whether it exists, so a
checkout without one degrades to "reference data is not installed" rather than
to an error.

Expected columns (the export this was written against):

    product_id, brand_name, manufacturer, price_inr, is_discontinued,
    dosage_form, pack_size, pack_unit, num_active_ingredients,
    primary_ingredient, primary_strength, active_ingredients,
    therapeutic_class, packaging_raw, manufacturer_raw
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enrichment import reference_index  # noqa: E402

REQUIRED_COLUMNS = {
    "brand_name", "manufacturer", "dosage_form", "pack_size",
    "primary_strength", "num_active_ingredients", "active_ingredients",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="Path to the reference CSV export.")
    parser.add_argument(
        "--out",
        default=reference_index.DEFAULT_PATH,
        help=f"Where to write the index (default: {reference_index.DEFAULT_PATH})",
    )
    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"No such file: {args.csv_path}", file=sys.stderr)
        return 1

    # Checked before the build rather than after: a differently-shaped export
    # would otherwise produce an index full of empty columns that looks fine
    # until the catalogue starts proposing blanks.
    import csv as csv_module

    csv_module.field_size_limit(10_000_000)
    with open(args.csv_path, newline="", encoding="utf-8") as handle:
        header = next(csv_module.reader(handle), [])
    missing = REQUIRED_COLUMNS - set(header)
    if missing:
        print(f"CSV is missing expected columns: {', '.join(sorted(missing))}", file=sys.stderr)
        return 1

    started = time.time()
    result = reference_index.build(args.csv_path, args.out)
    print(
        f"Indexed {result['indexed']:,} products "
        f"({result['skipped']:,} skipped) into {result['path']} "
        f"in {time.time() - started:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
