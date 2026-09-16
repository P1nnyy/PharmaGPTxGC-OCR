"""Rebuilds data/gstn/hsn_master.json from GSTN's published HSN workbook.

The master is not something to hand-edit. GSTR-1 Table 12 is a dropdown fed by
GSTN's own list, so the only list worth validating against is theirs, and the
only defensible way to hold it is to regenerate it from the published file and
record where that file came from.

    curl -O https://tutorial.gst.gov.in/downloads/HSN_SAC.xlsx
    python scripts/build_hsn_master.py HSN_SAC.xlsx

The workbook carries two sheets. Only HSN_MSTR is read; SAC_MSTR is the service
accounting codes, which a pharmacy does not file in Table 12.

Three things are cleaned up on the way through, all of them artefacts of the
spreadsheet rather than of the tariff:

* **Lost leading zeros.** Codes in chapters 01-09 whose cell was typed as a
  number arrive five or seven digits long - `30559` is `030559`. They are
  padded back to the next valid length. Codes that kept their zero because the
  cell was text (`0101`) are already right.
* **Codes with a space** (`2307 00`). Stripped to digits.
* **`_x000D_`**, Excel's escaped carriage return, and runs of whitespace.

Every one of those normalisations collides with a well-formed row that is
already in the sheet, so they resolve to duplicates rather than to new codes.
The first spelling of a code wins and the count of dropped duplicates is
printed, because a sudden change in that number means the sheet's shape moved
and this script should be re-read before its output is trusted.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "gstn" / "hsn_master.json"

SOURCE_URL = "https://tutorial.gst.gov.in/downloads/HSN_SAC.xlsx"

# The lengths the tariff actually uses. A code that arrives shorter than one of
# these lost a leading zero to a numeric cell and is padded up to it.
VALID_LENGTHS = (2, 4, 6, 8)


def clean_description(text: object) -> str:
    """Excel artefacts out, tariff text left alone."""
    value = "" if text is None else str(text)
    value = value.replace("_x000D_", " ").replace("’", "'")
    value = re.sub(r"\s+", " ", value).strip()
    # Tariff headings end in a dangling colon where sub-headings follow them
    # in the printed schedule ("OTHER :"). Nothing follows here.
    return value.rstrip(" :").strip()


def normalize_code(raw: object) -> str:
    """Digits only, with a lost leading zero put back."""
    digits = "".join(ch for ch in str(raw).strip() if ch.isdigit())
    if not digits:
        return ""
    for length in VALID_LENGTHS:
        if len(digits) <= length:
            return digits.rjust(length, "0")
    return digits


def build(xlsx: Path) -> dict:
    sha256 = hashlib.sha256(xlsx.read_bytes()).hexdigest()

    workbook = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    sheet = workbook["HSN_MSTR"]

    rows = 0
    duplicates = 0
    codes: dict = {}
    for raw_code, raw_description in sheet.iter_rows(values_only=True):
        if raw_code is None or str(raw_code).strip() == "HSN_CD":
            continue
        rows += 1
        code = normalize_code(raw_code)
        if not code:
            continue
        if code in codes:
            duplicates += 1
            continue
        codes[code] = clean_description(raw_description)

    by_length = dict(sorted(Counter(len(c) for c in codes).items()))
    print(f"rows read        {rows}")
    print(f"codes kept       {len(codes)}")
    print(f"duplicates       {duplicates}")
    print(f"by digit length  {by_length}")
    print(f"sha256           {sha256}")

    return {
        "_comment": (
            "A stored GSTN HSN master. GSTR-1 Table 12 accepts only codes the "
            "portal itself lists, so a code that is merely plausible - a real "
            "product with a guessed classification - is rejected at filing "
            "rather than at entry. Validating against this list is what moves "
            "that failure back to the point where somebody can still fix it."
        ),
        "_scope": (
            "The complete GSTN HSN master, not a seed. Every code GSTN "
            "publishes is here, at 2, 4, 6 and 8 digits, because the digit "
            "length a shop must report depends on its turnover and a 6-digit "
            "filer cannot report a 4-digit code. The 2-digit chapter headings "
            "are part of GSTN's list but are never filable in Table 12; "
            "core.hsn enforces the 4/6/8 rule separately, so being in this "
            "file is necessary to file a code and not sufficient."
        ),
        "_extending": (
            "Do not hand-edit. Regenerate with scripts/build_hsn_master.py "
            "against a freshly downloaded workbook, which also refreshes the "
            "provenance below. Never add a code to make a bill pass - an "
            "unknown code means the product is misclassified, and filing it "
            "under a code the portal does not recognise fails the return."
        ),
        "_rates_are_elsewhere": (
            "Deliberately no rates here. An HSN says what a thing is; the rate "
            "it carries is effective-dated and lives in the rate table. "
            "Putting a rate beside a code would freeze it at whatever it was "
            "the day this was written. GSTN's workbook carries no rates "
            "either - they come from the CBIC rate notifications."
        ),
        "_provenance": {
            "source_url": SOURCE_URL,
            "source_sheet": "HSN_MSTR",
            # The download's own timestamp, not today's date. Rebuilding from a
            # workbook fetched last month should say last month.
            "retrieved_on": date.fromtimestamp(xlsx.stat().st_mtime).isoformat(),
            "sha256": sha256,
            "bytes": xlsx.stat().st_size,
            "rows_in_sheet": rows,
            "codes": len(codes),
            "duplicates_dropped": duplicates,
            "codes_by_digit_length": by_length,
            "built_by": "scripts/build_hsn_master.py",
        },
        "codes": {code: codes[code] for code in sorted(codes)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xlsx", type=Path, help="GSTN's HSN_SAC.xlsx")
    args = parser.parse_args()

    if not args.xlsx.exists():
        print(f"no such file: {args.xlsx}", file=sys.stderr)
        return 1

    master = build(args.xlsx)
    OUT.write_text(json.dumps(master, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote            {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
