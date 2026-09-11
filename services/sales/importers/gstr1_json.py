"""The GSTR-1 JSON importer — the universal fallback.

Almost every Indian billing package can emit a GSTR-1 JSON, so a shop whose
day-book export we have never seen can still get its outward supplies in
through this. It is also the least ambiguous source we accept: the schema
states taxable value and tax as separate fields, so unlike a printed bill there
is nothing to infer about whether a figure includes tax.

That is what makes the reconciliation here strict. When a file states a rate, a
taxable value and a tax amount that do not agree with each other, the file is
internally inconsistent, and importing it would carry the inconsistency into a
return. It is rejected instead, naming the row.

B2CS is what a pharmacy counter produces: supplies to unregistered persons,
reported per place of supply and rate rather than per invoice. One Sale is
created per place of supply, because two states are two different figures in
the return rather than one.
"""

import json
from typing import Any, Optional

from core.money import halve_tax, parse_rupees_to_paise, round_to_rupee, tax_on_exclusive
from core.tax_periods import is_valid_period, period_bounds
from services.sales.importers.base import ImportRejected


def _paise(value: Any) -> int:
    parsed = parse_rupees_to_paise(value)
    return parsed if parsed is not None else 0


def _rate_bp(value: Any) -> Optional[int]:
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


class Gstr1JsonAdapter:
    name = "gstr1_json"
    label = "GSTR-1 JSON (GSTN return)"

    def sniff(self, data: bytes, filename: Optional[str] = None) -> bool:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        # `fp` (filing period) plus a GSTIN is the shape no other format we
        # accept happens to have; one of the supply tables must be present too,
        # so an empty envelope is not claimed by this adapter.
        looks_like_a_return = "fp" in payload and "gstin" in payload
        has_a_table = any(key in payload for key in ("b2cs", "b2b", "b2cl", "nil", "hsn"))
        return bool(looks_like_a_return and has_a_table)

    def parse(self, data: bytes, filename: Optional[str] = None, **options: Any) -> "list[dict]":
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImportRejected("That file is not readable JSON.") from exc
        if not isinstance(payload, dict):
            raise ImportRejected("That JSON is not a GSTR-1 return.")

        period = payload.get("fp")
        if not period:
            raise ImportRejected("The file does not say which tax period it covers (`fp`).")
        if not is_valid_period(str(period)):
            raise ImportRejected(
                f"{period!r} is not a tax period. GSTR-1 states it as MMYYYY, e.g. 092026."
            )
        period = str(period)
        # A period aggregate is dated to the day the period closes: it covers
        # the whole month, and any single day inside it would be a fiction.
        _, last_day = period_bounds(period)

        by_pos: dict[str, list[dict]] = {}
        for index, row in enumerate(payload.get("b2cs") or [], start=1):
            block = self._read_b2cs_row(row, index)
            by_pos.setdefault(block.pop("place_of_supply"), []).append(block)

        nil = self._read_nil_section(payload.get("nil") or {})

        if not by_pos and not any(nil.values()):
            raise ImportRejected(
                "There is nothing to import: the file declares no B2CS supplies "
                "and no exempt, nil-rated or non-GST amounts."
            )

        # The untaxed buckets are stated once for the return, not per place of
        # supply, so they attach to the first record rather than being copied
        # onto each — copying would multiply them.
        drafts = []
        for position, (place_of_supply, blocks) in enumerate(sorted(by_pos.items())):
            drafts.append(
                self._draft(period, last_day, place_of_supply, blocks, nil if position == 0 else None)
            )
        if not drafts:
            drafts.append(self._draft(period, last_day, payload.get("gstin", "")[:2], [], nil))
        return drafts

    def _read_b2cs_row(self, row: dict, index: int) -> dict:
        rate_bp = _rate_bp(row.get("rt"))
        if rate_bp is None:
            raise ImportRejected(f"B2CS row {index} has no readable rate.")

        taxable = _paise(row.get("txval"))
        cgst = _paise(row.get("camt"))
        sgst = _paise(row.get("samt"))
        igst = _paise(row.get("iamt"))

        # Inter-state B2CS carries IGST instead of the two halves. It is not a
        # counter sale, but it is in the file, and dropping it would understate
        # the return — so it is read and split for storage while the total
        # tax stays exactly what the file declared.
        if igst and not (cgst or sgst):
            cgst, sgst = halve_tax(igst)

        declared_tax = cgst + sgst
        expected_tax = tax_on_exclusive(taxable, rate_bp)
        # One paisa of slack, and one only: an odd total cannot halve evenly,
        # so a file that rounds its own halves differently is still consistent.
        # Anything wider than that is a real disagreement.
        if abs(declared_tax - expected_tax) > 1:
            raise ImportRejected(
                f"B2CS row {index} does not add up: at {rate_bp / 100:g}% on "
                f"{taxable / 100:.2f} the tax should be {expected_tax / 100:.2f}, "
                f"but the file declares {declared_tax / 100:.2f}. Nothing was imported."
            )

        return {
            "place_of_supply": str(row.get("pos") or "").strip(),
            "rate_bp": rate_bp,
            "taxable_paise": taxable,
            "cgst_paise": cgst,
            "sgst_paise": sgst,
            "gross_paise": taxable + declared_tax,
        }

    def _read_nil_section(self, nil: dict) -> dict:
        exempt = nil_rated = non_gst = 0
        for row in nil.get("inv") or []:
            exempt += _paise(row.get("expt_amt"))
            nil_rated += _paise(row.get("nil_amt"))
            non_gst += _paise(row.get("ngsup_amt"))
        return {"exempt_paise": exempt, "nil_rated_paise": nil_rated, "non_gst_paise": non_gst}

    def _draft(
        self, period: str, sale_date: str, place_of_supply: str,
        blocks: "list[dict]", nil: Optional[dict],
    ) -> dict:
        nil = nil or {"exempt_paise": 0, "nil_rated_paise": 0, "non_gst_paise": 0}
        merged: dict[int, dict] = {}
        for block in blocks:
            existing = merged.setdefault(
                block["rate_bp"],
                {"rate_bp": block["rate_bp"], "taxable_paise": 0, "cgst_paise": 0,
                 "sgst_paise": 0, "gross_paise": 0},
            )
            for field in ("taxable_paise", "cgst_paise", "sgst_paise", "gross_paise"):
                existing[field] += block[field]

        ordered = [merged[rate] for rate in sorted(merged)]
        taxable = sum(b["taxable_paise"] for b in ordered)
        cgst = sum(b["cgst_paise"] for b in ordered)
        sgst = sum(b["sgst_paise"] for b in ordered)
        untaxed = nil["exempt_paise"] + nil["nil_rated_paise"] + nil["non_gst_paise"]
        grand_total, round_off = round_to_rupee(taxable + cgst + sgst + untaxed)

        return {
            "sale_date": sale_date,
            "tax_period": period,
            "place_of_supply": place_of_supply,
            "rate_blocks": ordered,
            "taxable_paise": taxable,
            "cgst_paise": cgst,
            "sgst_paise": sgst,
            **nil,
            "round_off_paise": round_off,
            "grand_total_paise": grand_total,
            # A return says what was supplied, never how it was paid for.
            "payments": [],
            "rate_source": "gstr1",
            # Period-level totals. No lines behind them, and reporting has to
            # know that before it computes anything item-level.
            "is_aggregate": True,
            "bill_number": None,
        }
