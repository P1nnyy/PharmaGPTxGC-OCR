"""The GSTR-1 JSON, in the shape the GSTN offline utility reads.

This is the one place in the engine where rupees exist. Everything upstream is
integer paise; the portal's schema is rupees to two decimals, so the conversion
happens here, once, on the way out - and never on the way back in.

The schema is the portal's, not ours, which is why the keys are terse and
unlovely (`txval`, `camt`, `iamt`, `sply_ty`). They are reproduced exactly
rather than renamed to something readable: a key that reads nicely and is
spelled differently from what the utility expects is a file that fails to
import, and it fails at the end of the month.

Two conventions worth knowing when reading this:

  * Rates are percentages, not basis points. 1200 bp leaves here as `12`.
  * Dates are `dd-mm-yyyy`, which is neither ISO nor what is stored.
"""

from decimal import Decimal
from typing import Optional

from core.hsn import describe

# Table 8's four rows, in the portal's own vocabulary. `INTRB` is inter-state
# and `INTRA` is intra-state, which are one character apart and mean opposite
# things - hence the mapping rather than string building.
_NIL_SUPPLY_TYPES = {
    ("INTER", True): "INTRB2B",
    ("INTRA", True): "INTRAB2B",
    ("INTER", False): "INTRB2C",
    ("INTRA", False): "INTRAB2C",
}

# Document-type code in Table 13. 1 is "Invoices for outward supply".
_DOC_TYPE_OUTWARD_INVOICE = 1


def rupees(paise: int) -> float:
    """Integer paise to the rupee figure the portal expects.

    Exact by construction: paise are hundredths of a rupee, so the division is
    a decimal shift rather than a rounding. Via Decimal so that the float
    handed to `json` is the nearest double to an exact two-place decimal, not
    the accumulation of a binary division.
    """
    return float(Decimal(paise) / Decimal(100))


def rate_percent(rate_bp: int) -> float:
    """1200 basis points as the `12` the schema wants."""
    value = Decimal(rate_bp) / Decimal(100)
    return int(value) if value == value.to_integral_value() else float(value)


def gstn_date(iso_date: str) -> str:
    """`2026-09-05` as `05-09-2026`."""
    parts = (iso_date or "").split("-")
    if len(parts) != 3:
        return iso_date or ""
    year, month, day = parts
    return f"{day[:2]}-{month[:2]}-{year}"


def _items(rate_blocks: list) -> list:
    """A document's rate blocks as the schema's numbered item list."""
    return [
        {
            "num": index,
            "itm_det": {
                "rt": rate_percent(block["rate_bp"]),
                "txval": rupees(block["taxable_paise"]),
                "camt": rupees(block["cgst_paise"]),
                "samt": rupees(block["sgst_paise"]),
                "iamt": rupees(block["igst_paise"]),
                "csamt": rupees(block["cess_paise"]),
            },
        }
        for index, block in enumerate(rate_blocks, start=1)
    ]


def _b2b_section(entries: list) -> list:
    """Table 4A, grouped by the customer's GSTIN as the schema requires."""
    by_ctin: dict = {}
    for entry in entries:
        by_ctin.setdefault(entry.customer_gstin, []).append(entry)
    return [
        {
            "ctin": ctin,
            "inv": [
                {
                    "inum": entry.bill_number or entry.document_id,
                    "idt": gstn_date(entry.sale_date),
                    "val": rupees(entry.invoice_value_paise),
                    "pos": entry.place_of_supply,
                    # No reverse charge on an ordinary outward supply, and no
                    # e-commerce operator behind a pharmacy counter.
                    "rchrg": "N",
                    "inv_typ": "R",
                    "itms": _items(entry.rate_blocks),
                }
                for entry in invoices
            ],
        }
        for ctin, invoices in sorted(by_ctin.items())
    ]


def _b2cl_section(entries: list) -> list:
    """Table 5, grouped by place of supply."""
    by_pos: dict = {}
    for entry in entries:
        by_pos.setdefault(entry.place_of_supply, []).append(entry)
    return [
        {
            "pos": pos,
            "inv": [
                {
                    "inum": entry.bill_number or entry.document_id,
                    "idt": gstn_date(entry.sale_date),
                    "val": rupees(entry.invoice_value_paise),
                    "itms": _items(entry.rate_blocks),
                }
                for entry in invoices
            ],
        }
        for pos, invoices in sorted(by_pos.items())
    ]


def _b2cs_section(buckets: list) -> list:
    """Table 7. One flat row per (supply type, place of supply, rate)."""
    return [
        {
            "sply_ty": bucket.supply_type,
            "pos": bucket.place_of_supply,
            # "OE" is other-than-e-commerce, which every counter sale is.
            "typ": "OE",
            "rt": rate_percent(bucket.rate_bp),
            "txval": rupees(bucket.taxable_paise),
            "camt": rupees(bucket.cgst_paise),
            "samt": rupees(bucket.sgst_paise),
            "iamt": rupees(bucket.igst_paise),
            "csamt": rupees(bucket.cess_paise),
        }
        for bucket in buckets
    ]


def _nil_section(rows: list) -> dict:
    return {
        "inv": [
            {
                "sply_ty": _NIL_SUPPLY_TYPES[(row.supply_type, row.registered)],
                "expt_amt": rupees(row.exempted_paise),
                "nil_amt": rupees(row.nil_rated_paise),
                "ngsup_amt": rupees(row.non_gst_paise),
            }
            for row in rows
        ]
    }


def _hsn_rows(rows: list) -> list:
    return [
        {
            "num": index,
            "hsn_sc": row.hsn,
            "desc": (describe(row.hsn) or "")[:30],
            "uqc": row.uqc,
            "qty": float(row.quantity),
            "rt": rate_percent(row.rate_bp),
            "txval": rupees(row.taxable_paise),
            "camt": rupees(row.cgst_paise),
            "samt": rupees(row.sgst_paise),
            "iamt": rupees(row.igst_paise),
            "csamt": rupees(row.cess_paise),
        }
        for index, row in enumerate(rows, start=1)
    ]


def _hsn_section(summary) -> dict:
    """Table 12, with B2B and B2C kept apart as the current schema requires."""
    return {
        "hsn_b2b": _hsn_rows(summary.b2b),
        "hsn_b2c": _hsn_rows(summary.b2c),
    }


def _doc_issue_section(issued) -> dict:
    return {
        "doc_det": [
            {
                "doc_num": _DOC_TYPE_OUTWARD_INVOICE,
                "docs": [
                    {
                        "num": index,
                        "from": series.opening_number or "",
                        "to": series.closing_number or "",
                        "totnum": series.total_issued,
                        "cancel": series.cancelled,
                        "net_issue": series.net_issued,
                    }
                    for index, series in enumerate(issued.series, start=1)
                ],
            }
        ]
    }


def build_payload(
    tables: dict,
    identity: dict,
    filing_period,
    gross_turnover_paise: Optional[int] = None,
) -> dict:
    """The complete GSTR-1 JSON for a filing period.

    `fp` is the last month of the window. For a monthly filer that is the month
    itself; for a QRMP filer the portal identifies a quarterly return by the
    month it ends in, which is why this reads the resolved filing period rather
    than the period the user happened to click.
    """
    payload = {
        "gstin": identity.get("gstin"),
        "fp": filing_period.months[-1] if filing_period.months else None,
        "filing_frequency": filing_period.frequency,
        "gt": rupees(gross_turnover_paise or 0),
        "cur_gt": rupees(gross_turnover_paise or 0),
        "b2b": _b2b_section(tables["b2b"]),
        "b2cl": _b2cl_section(tables["b2cl"]),
        "b2cs": _b2cs_section(tables["b2cs"].buckets),
        "nil": _nil_section(tables["nil_exempt"]),
        "hsn": _hsn_section(tables["hsn"]),
        "doc_issue": _doc_issue_section(tables["documents"]),
    }
    # The portal rejects an empty array where it expects a section to be
    # absent, so sections with nothing in them are dropped rather than sent
    # empty. `nil`, `hsn` and `doc_issue` always go: they are statements about
    # the whole period, and omitting one claims something different from
    # stating it as zero.
    for key in ("b2b", "b2cl", "b2cs"):
        if not payload[key]:
            payload.pop(key)
    return payload
