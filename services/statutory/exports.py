"""CSV and Excel exports of the report pack.

Both formats are rendered from the *same pack dictionary* the screen reads, and
from one column specification per report. That is the whole design: a figure
cannot differ between the screen, the CSV and the spreadsheet, because there is
only one figure and one list of columns. An export built by a separate query -
or, worse, assembled in the browser - is an export that can disagree with what
somebody checked before downloading it.

Every export carries a header block naming the shop, its GSTIN, the period and
when the file was made. A register handed to an accountant with no period on it
is a register they have to ask about, and a spreadsheet outlives the screen it
came from.

Money is written as a plain number, not as "₹1,234.56". An accountant's first
action is to sum a column, and a currency-formatted string sums to zero. The
rupee symbol belongs in the cell *format* - which the Excel export sets and CSV
cannot carry.
"""

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

# Column kinds. `money` is the one that matters: it decides both that the value
# is unwrapped from a figure and that it is written as a number.
TEXT, MONEY, NUMBER, DATE, BOOL, LIST = "text", "money", "number", "date", "bool", "list"


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    kind: str = TEXT


# One specification per report, shared by CSV, Excel and the print stylesheet's
# column order. Adding a column in one place adds it everywhere, which is the
# only way three renderers stay in step.
COLUMNS: dict = {
    "purchase_register": (
        Column("invoice_date", "Date", DATE),
        Column("invoice_number", "Invoice no."),
        Column("seller_name", "Supplier"),
        Column("seller_gstin", "Supplier GSTIN"),
        Column("supply_type", "Supply"),
        Column("taxable", "Taxable value", MONEY),
        Column("discount", "Discount", MONEY),
        Column("cgst", "CGST", MONEY),
        Column("sgst", "SGST", MONEY),
        Column("igst", "IGST", MONEY),
        Column("tax_total", "Total tax", MONEY),
        Column("grand_total", "Invoice value", MONEY),
        Column("itc_eligible", "ITC eligible", BOOL),
        Column("itc_blocked_reason", "ITC blocked because"),
        Column("status", "Status"),
    ),
    "sales_register": (
        Column("sale_date", "Date", DATE),
        Column("bill_number", "Bill no."),
        Column("document_type", "Document"),
        Column("capture_mode", "Captured as"),
        Column("customer_name", "Customer"),
        Column("customer_gstin", "Customer GSTIN"),
        Column("place_of_supply", "Place of supply"),
        Column("supply_type", "Supply"),
        Column("rates", "Rates %", LIST),
        Column("payment_methods", "Paid by", LIST),
        Column("taxable", "Taxable value", MONEY),
        Column("cgst", "CGST", MONEY),
        Column("sgst", "SGST", MONEY),
        Column("igst", "IGST", MONEY),
        Column("untaxed", "Nil / exempt", MONEY),
        Column("round_off", "Round off", MONEY),
        Column("grand_total", "Bill value", MONEY),
        Column("status", "Status"),
        Column("counts_in_return", "In return", BOOL),
    ),
    "hsn_outward": (
        Column("hsn", "HSN"),
        Column("description", "Description"),
        Column("uqc", "UQC"),
        Column("uqc_status", "UQC status"),
        Column("hsn_status", "HSN status"),
        Column("rate", "Rate %", NUMBER),
        Column("quantity", "Quantity", NUMBER),
        Column("taxable", "Taxable value", MONEY),
        Column("cgst", "CGST", MONEY),
        Column("sgst", "SGST", MONEY),
        Column("igst", "IGST", MONEY),
        Column("total_value", "Total value", MONEY),
    ),
    "hsn_inward": (
        Column("hsn", "HSN"),
        Column("description", "Description"),
        Column("uqc", "UQC"),
        Column("uqc_status", "UQC status"),
        Column("pack_as_printed", "Pack as printed"),
        Column("hsn_status", "HSN status"),
        Column("rate", "Rate %", NUMBER),
        Column("quantity", "Quantity", NUMBER),
        Column("line_count", "Lines", NUMBER),
        Column("taxable", "Taxable value", MONEY),
    ),
    "document_series": (
        Column("series_prefix", "Series"),
        Column("opening_number", "From"),
        Column("closing_number", "To"),
        Column("total_issued", "Issued", NUMBER),
        Column("cancelled", "Cancelled", NUMBER),
        Column("net_issued", "Net", NUMBER),
        Column("gaps", "Gaps", LIST),
        Column("duplicates", "Duplicates", LIST),
    ),
    "itc_reversals": (
        Column("tax_period", "Period"),
        Column("trigger", "Trigger"),
        Column("statutory_reference", "Provision"),
        Column("gstr3b_table", "3B table"),
        Column("is_permanent", "Permanent", BOOL),
        Column("cgst", "CGST", MONEY),
        Column("sgst", "SGST", MONEY),
        Column("igst", "IGST", MONEY),
        Column("cess", "Cess", MONEY),
        Column("total", "Total", MONEY),
        Column("source_invoice_number", "Source invoice"),
        Column("source_seller_name", "Supplier"),
        Column("reason", "Reason"),
        Column("note", "Note"),
    ),
}

# Reports whose shape is not a flat row list get their own extractor below.
_SECTIONED = {"gstr1", "gstr3b", "hsn_summary"}


def _cell(value: Any, kind: str) -> Any:
    """Unwraps a figure and normalises a value for a spreadsheet cell."""
    if isinstance(value, dict) and "paise" in value and "value" in value:
        return value["value"]
    if value is None:
        return ""
    if kind == BOOL:
        return "Yes" if value else "No"
    if kind == LIST:
        return ", ".join(str(v) for v in value) if value else ""
    return value


def _matrix(rows: list, columns: tuple) -> list:
    return [[_cell(row.get("cells", {}).get(c.key), c.kind) for c in columns] for row in rows]


def report_table(pack: dict, report_id: str) -> tuple:
    """`(title, columns, matrix)` for one report.

    The reports with sections rather than a single row list are flattened here
    so every export path downstream deals with one shape.
    """
    reports = pack["reports"]

    if report_id == "hsn_summary":
        outward = reports["hsn_summary"]["outward"]
        columns = COLUMNS["hsn_outward"]
        rows = outward["b2b"] + outward["b2c"]
        return "HSN summary (outward)", columns, _matrix(rows, columns)

    if report_id == "hsn_inward":
        columns = COLUMNS["hsn_inward"]
        return (
            "HSN summary (inward)",
            columns,
            _matrix(reports["hsn_summary"]["inward"]["rows"], columns),
        )

    if report_id == "gstr3b":
        columns = (
            Column("code", "Row"), Column("label", "Description"),
            Column("taxable", "Taxable value", MONEY), Column("igst", "IGST", MONEY),
            Column("cgst", "CGST", MONEY), Column("sgst", "SGST", MONEY),
            Column("cess", "Cess", MONEY), Column("note", "Note"),
        )
        worksheet = reports["gstr3b"]
        rows = worksheet["outward"] + worksheet["itc"]
        if worksheet.get("net_itc"):
            rows = rows + [worksheet["net_itc"]]
        matrix = [[_cell(row.get(c.key), c.kind) for c in columns] for row in rows]
        return "GSTR-3B worksheet", columns, matrix

    if report_id == "gstr1":
        columns = (
            Column("table", "Table"), Column("description", "Description"),
            Column("place_of_supply", "Place of supply"), Column("rate", "Rate %", NUMBER),
            Column("taxable", "Taxable value", MONEY), Column("cgst", "CGST", MONEY),
            Column("sgst", "SGST", MONEY), Column("igst", "IGST", MONEY),
        )
        tables = reports["gstr1"]["tables"]
        matrix = []
        for bucket in tables["b2cs"]:
            matrix.append([
                "7 — B2CS", f"{bucket['supply_type'].title()}-state",
                bucket["place_of_supply"], bucket["rate"],
                bucket["taxable"]["value"], bucket["cgst"]["value"],
                bucket["sgst"]["value"], bucket["igst"]["value"],
            ])
        for entry in tables["b2b"]:
            matrix.append([
                "4A — B2B", entry.get("customer_gstin") or "",
                entry["place_of_supply"], "",
                entry["invoice_value"]["value"], "", "", "",
            ])
        for entry in tables["b2cl"]:
            matrix.append([
                "5 — B2CL", entry.get("bill_number") or "",
                entry["place_of_supply"], "",
                entry["invoice_value"]["value"], "", "", "",
            ])
        for row in tables["nil_exempt"]:
            matrix.append([
                f"8 — {row['code']}", row["description"], "", "",
                row["total"]["value"], "", "", "",
            ])
        return "GSTR-1 preview", columns, matrix

    columns = COLUMNS[report_id]
    return (
        report_id.replace("_", " ").title(),
        columns,
        _matrix(reports[report_id]["rows"], columns),
    )


def _header_lines(pack: dict, title: str) -> list:
    """Who, what period, and when. A spreadsheet outlives its screen."""
    shop = pack.get("shop", {})
    period = pack.get("period", {})
    return [
        [title],
        [f"{shop.get('trade_name') or shop.get('legal_name') or ''}"],
        [f"GSTIN {shop.get('gstin') or '—'}"],
        [f"Period {period.get('label', '')} ({period.get('start_date')} to {period.get('end_date')})"],
        [f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"],
        [],
    ]


def to_csv(pack: dict, report_id: str) -> str:
    title, columns, matrix = report_table(pack, report_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for line in _header_lines(pack, title):
        writer.writerow(line)
    writer.writerow([c.header for c in columns])
    writer.writerows(matrix)

    failing = [c for c in pack.get("cross_checks", []) if not c.get("agrees")]
    if failing:
        # An export of a pack that does not reconcile has to say so on the
        # face of it. Somebody will open this file weeks later with no memory
        # of the banner they clicked past.
        writer.writerow([])
        writer.writerow(["UNRECONCILED — this pack failed cross-checks when exported:"])
        for check in failing:
            writer.writerow([check["label"], f"difference {check['difference']}"])
    return buffer.getvalue()


def to_xlsx(pack: dict, report_id: str) -> bytes:
    """One sheet, formatted so an accountant can sum it without cleaning it."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    title, columns, matrix = report_table(pack, report_id)
    book = Workbook()
    sheet = book.active
    # Excel refuses a sheet name over 31 characters or containing []:*?/\
    sheet.title = "".join(ch for ch in title if ch not in "[]:*?/\\")[:31]

    bold = Font(bold=True)
    for line in _header_lines(pack, title):
        sheet.append(line)
    sheet["A1"].font = Font(bold=True, size=14)

    header_row = sheet.max_row + 1
    sheet.append([c.header for c in columns])
    fill = PatternFill("solid", fgColor="EEF2FF")
    for index in range(1, len(columns) + 1):
        cell = sheet.cell(row=header_row, column=index)
        cell.font = bold
        cell.fill = fill
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    for row in matrix:
        sheet.append(row)

    # Money as a number with a rupee format: it sums, and it still reads as
    # currency. A pre-formatted string would do neither.
    money_format = '₹#,##,##0.00'
    for index, column in enumerate(columns, start=1):
        letter = get_column_letter(index)
        width = max(len(column.header), 12)
        for row in matrix:
            width = max(width, min(len(str(row[index - 1])), 40))
        sheet.column_dimensions[letter].width = width + 2
        if column.kind == MONEY:
            for row_index in range(header_row + 1, sheet.max_row + 1):
                sheet.cell(row=row_index, column=index).number_format = money_format

    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)

    failing = [c for c in pack.get("cross_checks", []) if not c.get("agrees")]
    if failing:
        sheet.append([])
        warning = sheet.max_row + 1
        sheet.append(["UNRECONCILED — this pack failed cross-checks when exported:"])
        sheet.cell(row=warning, column=1).font = Font(bold=True, color="9C1C1C")
        for check in failing:
            sheet.append([check["label"], f"difference {check['difference']}"])

    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def filename(pack: dict, report_id: str, extension: str) -> str:
    """A name that still means something in a folder of thirty of them."""
    period = (pack.get("period", {}).get("label") or "period").replace(" ", "-")
    gstin = pack.get("shop", {}).get("gstin") or "shop"
    return f"{report_id}-{gstin}-{period}.{extension}"


EXPORTABLE = tuple(COLUMNS) + ("gstr1", "gstr3b", "hsn_summary", "hsn_inward")


def is_exportable(report_id: str) -> bool:
    return report_id in EXPORTABLE
