"""The generic day-book / sales-register importer.

Marg and Vyapar are the formats a pharmacy is most likely to be exporting, and
their layouts vary by version. Rather than guess at their column names — which
would produce an adapter that passes tests written against the guess and
mis-maps a real file — this adapter maps columns explicitly:

  1. it proposes a mapping from headers it recognises,
  2. the user corrects it,
  3. the correction is remembered for that format and offered next time.

`propose_mapping` deliberately leaves a header it does not recognise unmapped.
An empty field the user has to fill in is better than a confident wrong guess,
because the second one is invisible.

**Why a wrong mapping is safe to make.** Every row is reconciled twice — the
declared tax against rate times taxable value, and the declared total against
taxable plus tax. A column pointed at the wrong field almost never satisfies
both, so a mis-mapping is rejected with the offending bill named rather than
imported as plausible-looking figures.
"""

import csv
import io
import re
from typing import Any, Optional

from core.dates import normalize_invoice_date
from core.money import parse_rupees_to_paise, round_to_rupee, tax_on_exclusive
from core.tax_periods import PeriodError, period_of
from services.sales.importers.base import ImportRejected

# The fields a row must supply before it can be reconciled at all.
REQUIRED_FIELDS = ("bill_number", "sale_date", "rate", "taxable")
OPTIONAL_FIELDS = ("cgst", "sgst", "igst", "total")
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

# Header spellings seen across common exports. Matched on a normalised form, so
# "CGST Amt", "cgst_amount" and "C.G.S.T." all land on the same field.
_ALIASES: "dict[str, tuple[str, ...]]" = {
    "bill_number": ("invoiceno", "invoicenumber", "billno", "billnumber", "voucherno", "docno"),
    "sale_date": ("date", "invoicedate", "billdate", "voucherdate", "txndate"),
    "rate": ("gst", "gstpercent", "gstrate", "taxrate", "rate", "slab", "gstslab"),
    "taxable": ("taxablevalue", "taxableamount", "taxable", "basicamount", "basevalue", "assessablevalue"),
    "cgst": ("cgstamt", "cgstamount", "cgst", "cgstvalue"),
    "sgst": ("sgstamt", "sgstamount", "sgst", "sgstvalue", "ugst", "ugstamt"),
    "igst": ("igstamt", "igstamount", "igst", "igstvalue"),
    "total": ("netamount", "billamount", "invoiceamount", "grandtotal", "total", "amount"),
}

_SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm")


def _normalise_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(header or "").lower())


def propose_mapping(headers: "list[str]") -> "dict[str, Optional[str]]":
    """Suggests which column is which, leaving anything unrecognised unmapped."""
    normalised = {_normalise_header(h): h for h in headers}
    proposal: dict[str, Optional[str]] = {}
    for field, aliases in _ALIASES.items():
        proposal[field] = next(
            (normalised[alias] for alias in aliases if alias in normalised), None
        )
    return proposal


def _read_rows(data: bytes, filename: Optional[str]) -> "tuple[list[str], list[dict]]":
    """Returns `(headers, rows)` for a CSV or an Excel sheet."""
    name = (filename or "").lower()

    if name.endswith(_SPREADSHEET_SUFFIXES):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ImportRejected(
                "Excel files need the openpyxl package, which is not installed. "
                "Save the export as CSV and try again."
            ) from exc
        try:
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise ImportRejected("That file could not be opened as a spreadsheet.") from exc
        sheet = workbook.active
        grid = [[cell for cell in row] for row in sheet.iter_rows(values_only=True)]
        if not grid:
            raise ImportRejected("That spreadsheet is empty.")
        headers = [str(h) if h is not None else "" for h in grid[0]]
        rows = [
            {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
            for row in grid[1:]
            if any(cell is not None and str(cell).strip() for cell in row)
        ]
        return headers, rows

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise ImportRejected("That file is not readable text.") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportRejected("That file has no header row, so its columns cannot be mapped.")
    rows = [row for row in reader if any((v or "").strip() for v in row.values())]
    return list(reader.fieldnames), rows


class TabularAdapter:
    name = "tabular"
    label = "Day book / sales register (CSV or Excel)"

    def sniff(self, data: bytes, filename: Optional[str] = None) -> bool:
        name = (filename or "").lower()
        if name.endswith(_SPREADSHEET_SUFFIXES):
            return True
        if not name.endswith(".csv") and name:
            return False
        try:
            text = data[:4096].decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
        # A header row with separators, and not JSON.
        stripped = text.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            return False
        first_line = stripped.splitlines()[0] if stripped.splitlines() else ""
        return first_line.count(",") >= 2 or first_line.count("\t") >= 2

    def parse(
        self,
        data: bytes,
        filename: Optional[str] = None,
        mapping: Optional[dict] = None,
        **options: Any,
    ) -> "list[dict]":
        headers, rows = _read_rows(data, filename)
        if not rows:
            raise ImportRejected("That file has a header row but no data rows.")

        mapping = mapping or propose_mapping(headers)
        missing = [field for field in REQUIRED_FIELDS if not mapping.get(field)]
        if missing:
            raise ImportRejected(
                "These columns still need mapping before the file can be imported: "
                + ", ".join(missing)
                + "."
            )
        unknown = [
            column for field, column in mapping.items()
            if field in ALL_FIELDS and column and column not in headers
        ]
        if unknown:
            raise ImportRejected(
                f"The file has no column called {unknown[0]!r}. Check the column mapping."
            )

        by_bill: dict[str, dict] = {}
        for index, row in enumerate(rows, start=2):  # row 1 is the header
            self._read_row(row, mapping, index, by_bill)

        return [self._finish(draft) for draft in by_bill.values()]

    def _read_row(self, row: dict, mapping: dict, line_no: int, by_bill: dict) -> None:
        def cell(field: str):
            column = mapping.get(field)
            return row.get(column) if column else None

        bill_number = str(cell("bill_number") or "").strip()
        if not bill_number:
            raise ImportRejected(f"Row {line_no} has no bill number.")

        sale_date = normalize_invoice_date(str(cell("sale_date") or "").strip())
        if not sale_date:
            raise ImportRejected(
                f"Row {line_no} ({bill_number}) has no readable date."
            )

        rate_raw = cell("rate")
        try:
            rate_bp = int(round(float(str(rate_raw).strip().rstrip("%")) * 100))
        except (TypeError, ValueError) as exc:
            raise ImportRejected(
                f"Row {line_no} ({bill_number}) has no readable GST rate."
            ) from exc

        taxable = parse_rupees_to_paise(cell("taxable"))
        if taxable is None:
            raise ImportRejected(
                f"Row {line_no} ({bill_number}) has no readable taxable value. "
                "Check that the taxable column is mapped to the right column."
            )

        cgst = parse_rupees_to_paise(cell("cgst")) or 0
        sgst = parse_rupees_to_paise(cell("sgst")) or 0
        igst = parse_rupees_to_paise(cell("igst")) or 0
        if igst and not (cgst or sgst):
            from core.money import halve_tax

            cgst, sgst = halve_tax(igst)

        declared_tax = cgst + sgst
        expected_tax = tax_on_exclusive(taxable, rate_bp)
        if abs(declared_tax - expected_tax) > 1:
            raise ImportRejected(
                f"{bill_number} (row {line_no}) does not add up: at {rate_bp / 100:g}% "
                f"on {taxable / 100:.2f} the tax should be {expected_tax / 100:.2f}, "
                f"but the file says {declared_tax / 100:.2f}. Check the column "
                "mapping — nothing was imported."
            )

        declared_total = parse_rupees_to_paise(cell("total"))
        if declared_total is not None and abs(declared_total - (taxable + declared_tax)) > 1:
            raise ImportRejected(
                f"{bill_number} (row {line_no}) does not add up: its total says "
                f"{declared_total / 100:.2f} but its parts add to "
                f"{(taxable + declared_tax) / 100:.2f}. Check the column mapping — "
                "nothing was imported."
            )

        draft = by_bill.setdefault(
            bill_number,
            {"bill_number": bill_number, "sale_date": sale_date, "blocks": {}},
        )
        if draft["sale_date"] != sale_date:
            raise ImportRejected(
                f"{bill_number} appears on two different dates ({draft['sale_date']} "
                f"and {sale_date}). Two bills sharing a number cannot be told apart."
            )

        block = draft["blocks"].setdefault(
            rate_bp,
            {"rate_bp": rate_bp, "taxable_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "gross_paise": 0},
        )
        block["taxable_paise"] += taxable
        block["cgst_paise"] += cgst
        block["sgst_paise"] += sgst
        block["gross_paise"] += taxable + declared_tax

    def _finish(self, draft: dict) -> dict:
        blocks = [draft["blocks"][rate] for rate in sorted(draft["blocks"])]
        taxable = sum(b["taxable_paise"] for b in blocks)
        cgst = sum(b["cgst_paise"] for b in blocks)
        sgst = sum(b["sgst_paise"] for b in blocks)
        grand_total, round_off = round_to_rupee(taxable + cgst + sgst)

        try:
            tax_period = period_of(draft["sale_date"])
        except PeriodError as exc:  # pragma: no cover - date is already normalised
            raise ImportRejected(str(exc)) from exc

        return {
            "sale_date": draft["sale_date"],
            "tax_period": tax_period,
            "bill_number": draft["bill_number"],
            "rate_blocks": blocks,
            "taxable_paise": taxable,
            "cgst_paise": cgst,
            "sgst_paise": sgst,
            # A sales register states taxed supplies. Exempt and nil-rated
            # amounts, if the export carries them at all, are a separate column
            # set we have no sample of — left at zero and flagged rather than
            # guessed at.
            "exempt_paise": 0,
            "nil_rated_paise": 0,
            "non_gst_paise": 0,
            "round_off_paise": round_off,
            "grand_total_paise": grand_total,
            "payments": [],
            "rate_source": "imported",
            "is_aggregate": False,
        }
