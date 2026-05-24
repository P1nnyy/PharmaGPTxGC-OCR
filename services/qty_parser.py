"""
Quantity Parser for Indian Pharmaceutical Invoice Formats.

Handles compound, scheme, and pack quantity notations commonly found in
Indian pharma distributor invoices. Normalizes all formats into a structured
ParsedQuantity model with billed/free/total decomposition.

Supported formats:
    "2.750+.250"    → 2.75 billed + 0.25 free (scheme notation)
    "4.50+.50"      → 4.5 billed + 0.5 free
    "2+1"           → 2 billed + 1 free (integer scheme)
    "1*15 2"        → 2 billed, pack size 15 (fused qty/pack notation)
    "3×1×15"        → 45 total (nested pack: 3×1×15)
    "2 (1×10)"      → 20 total (2 units of 10-strip pack)
    "2"             → 2 billed, plain integer
    "1.84"          → 1.84 billed, plain decimal

OCR noise handling:
    "2,750+,250"    → comma-as-decimal (Indian OCR artifact)
    "2.750 + .250"  → whitespace around operator
    "2.750+0.250"   → leading zero on free component
"""

import re
from typing import Optional, Tuple
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pydantic import BaseModel, Field
from core.logger import logger


class ParsedQuantity(BaseModel):
    """Structured representation of a parsed pharmaceutical quantity.

    Attributes:
        billed_qty: Units charged to the buyer (used for Amount calculation).
        free_qty: Units given free under scheme/initiative (Amount = 0 for these).
        total_qty: billed_qty + free_qty (total units dispatched).
        pack_size: If pack notation detected, the computed pack size. None otherwise.
        is_scheme: True if the quantity contains a scheme/free component.
        raw: Original raw string before parsing.
        parse_method: Which regex branch matched (for debugging).
    """
    billed_qty: Decimal = Field(default=Decimal("0"))
    free_qty: Decimal = Field(default=Decimal("0"))
    total_qty: Decimal = Field(default=Decimal("0"))
    pack_size: Optional[int] = None
    is_scheme: bool = False
    raw: str = ""
    parse_method: str = "none"
    qty_parse_extracted_expression: Optional[str] = None
    qty_parse_rejected_reason: Optional[str] = None
    
    # NEW: Fused Qty/Pack parse diagnostic metadata fields
    qty_pack_fused_parse_used: bool = False
    qty_pack_original_text: Optional[str] = None
    qty_pack_parsed_billed_qty: Optional[Decimal] = None

    model_config = {"json_encoders": {Decimal: str}}  # Pydantic v2 ConfigDict


def _normalize_ocr_noise(raw: str) -> str:
    """Clean OCR artifacts from quantity strings before parsing.

    Args:
        raw: Raw OCR text from a quantity cell.

    Returns:
        Cleaned string with normalized decimal separators and whitespace.
    """
    if not raw:
        return ""
    text = raw.strip()

    # Replace common OCR multiplication symbols with ASCII '*'
    # ×  (U+00D7), ✕ (U+2715), x/X when surrounded by digits
    text = text.replace("×", "*").replace("✕", "*")
    # Lowercase 'x' between digits: "3x1x15" → "3*1*15"
    # Must loop because matches overlap (the trailing digit of one match
    # is the leading digit of the next: 3x1x15 → first match consumes '3x1')
    prev = None
    while prev != text:
        prev = text
        text = re.sub(
            r'(\d)\s*[xX]\s*(\d)',  # digit-x-digit pattern
            r'\1*\2',
            text
        )

    # Handle comma-as-decimal: "2,750+,250" → "2.750+.250"
    # Heuristic: in qty context, commas followed by 1-3 digits at end/before operator
    # are decimal separators, not thousands separators.
    # Indian qty values are small (< 1000), so commas are never thousands separators.
    text = text.replace(",", ".")

    # OCR Digit Corruption Patterns (Context-Aware)
    # Only replace O/I/B if surrounded by digits or near decimal points
    text = re.sub(r'(?<=\d)[OoOo](?=\d|\.|$)', '0', text)
    text = re.sub(r'(?<=\d|\.)[lI](?=\d|\.|$)', '1', text)
    text = re.sub(r'(?<=\d)[B8](?=\d|\.|$)', '8', text)

    # Normalize whitespace around operators but preserve the operator
    text = re.sub(r'\s*\+\s*', '+', text)  # collapse spaces around '+'
    text = re.sub(r'\s*\*\s*', '*', text)  # collapse spaces around '*'

    return text


def _safe_decimal(value: str) -> Decimal:
    """Convert a string to Decimal, handling edge cases.

    Args:
        value: Numeric string, possibly with leading dot (e.g., ".250").

    Returns:
        Decimal value.

    Raises:
        InvalidOperation: If the string cannot be parsed as a number.
    """
    cleaned = value.strip()
    if not cleaned:
        return Decimal("0")
    # Leading dot without zero: ".250" → "0.250"
    if cleaned.startswith("."):
        cleaned = "0" + cleaned
    return Decimal(cleaned)


def _extract_quantity_expression(text: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Pull the most likely quantity expression out of a noisy OCR cell.

    Preference is intentionally conservative:
    1. Scheme quantities with a plus sign, e.g. 2.750+.250, 10+2.
    2. Pack/multiply quantities, e.g. 1*15.
    3. A lone small integer/trailing-dot quantity only when the whole cell is numeric.
    """
    scheme_match = re.search(r'(?<![\d.])(\d{1,4}(?:\.\d{1,4})?\+\d{1,4}(?:\.\d{1,4})?)(?![\d.])', text)
    if scheme_match:
        expr = scheme_match.group(1)
        return expr, expr if expr != text else None, None

    leading_dot_scheme = re.search(r'(?<![\d.])(\d{1,4}(?:\.\d{1,4})?\+\.?\d{1,4})(?![\d.])', text)
    if leading_dot_scheme:
        expr = leading_dot_scheme.group(1)
        return expr, expr if expr != text else None, None

    pack_match = re.search(r'(?<![\d.])(\d{1,4}(?:\.\d{1,3})?(?:\*\d{1,4}(?:\.\d{1,3})?)+)(?![\d.])', text)
    if pack_match:
        expr = pack_match.group(1)
        return expr, expr if expr != text else None, None

    if re.fullmatch(r'\d{1,4}\.?', text):
        expr = text.rstrip(".")
        return expr, expr if expr != text else None, None

    if re.fullmatch(r'\d{1,4}(?:\.\d{1,3})?', text):
        return text, None, None

    return text, None, "no_quantity_expression_found"


def parse_quantity(raw: str) -> ParsedQuantity:
    """Parse an Indian pharma quantity string into structured components.

    Processes the raw string through a prioritized regex pipeline:
    1. Fused Qty/Pack notation: pack-like prefix + standalone integer (e.g. "1-10 2")
    2. Standalone Pack size: pack pattern alone, should not parse as quantity (e.g. "1*10")
    3. Scheme notation: billed+free (e.g., "2.750+.250")
    4. Parenthesized pack: qty (pack_expr) (e.g., "2 (1×10)")
    5. Pack/multiply notation: a*b*c (e.g., "3×1×15")
    6. Plain numeric: integer or decimal (e.g., "2", "1.84")

    Args:
        raw: Raw text from a quantity cell in an OCR-extracted invoice table.

    Returns:
        ParsedQuantity with billed_qty, free_qty, total_qty, etc.
    """
    if not raw or not raw.strip():
        return ParsedQuantity(
            raw=raw or "",
            parse_method="empty",
            qty_parse_rejected_reason="empty",
        )

    text = _normalize_ocr_noise(raw)
    original = raw.strip()

    # ── NEW: PATTERN 1: Fused Qty/Pack notation ──
    # If the quantity cell has a pack-like pattern followed by a space and a trailing standalone number.
    # Examples: "1*10 2", "1-10 2", "MIS 3", "1:10= 2"
    fused_match = re.search(r"^(.*?)\s+(\d+(?:\.\d+)?)$", text.strip())
    if fused_match:
        prefix = fused_match.group(1).strip()
        trailing_str = fused_match.group(2).strip()
        
        # Determine if the prefix looks like a pack size
        is_pack_prefix = False
        if prefix.upper() == "MIS":
            is_pack_prefix = True
        elif re.search(r"\b\d+\s*(?:GM|ML|MG|TAB|CAP|S|'S|NOS)\b", prefix, re.IGNORECASE):
            is_pack_prefix = True
        elif re.search(r"\b\d+[\*\-xX×/:=]\d+[\*\-xX×/:=]?\d*=?", prefix):
            is_pack_prefix = True
            
        if is_pack_prefix:
            try:
                billed = _safe_decimal(trailing_str)
                # Compute pack size by multiplying factors in prefix
                pack_sz = None
                mult_match = re.search(r"(\d+)[\*\-xX×/:=](\d+)", prefix)
                if mult_match:
                    try:
                        p1 = int(mult_match.group(1))
                        p2 = int(mult_match.group(2))
                        pack_sz = p1 * p2
                    except ValueError:
                        pass
                if pack_sz is None:
                    # Look for trailing/leading units GM/ML/etc
                    unit_match = re.search(r"\b(\d+)\s*(?:GM|ML|MG|TAB|CAP|S|'S|NOS)\b", prefix, re.IGNORECASE)
                    if unit_match:
                        try:
                            pack_sz = int(unit_match.group(1))
                        except ValueError:
                            pass

                logger.info(
                    f"qty_parser: detected fused qty/pack '{original}' -> "
                    f"billed_qty={billed}, pack_size={pack_sz}"
                )
                return ParsedQuantity(
                    billed_qty=billed,
                    free_qty=Decimal("0"),
                    total_qty=billed,
                    pack_size=pack_sz,
                    is_scheme=False,
                    raw=original,
                    parse_method="qty_pack_fused_extracted",
                    qty_parse_extracted_expression=trailing_str,
                    qty_pack_fused_parse_used=True,
                    qty_pack_original_text=original,
                    qty_pack_parsed_billed_qty=billed,
                )
            except InvalidOperation:
                pass

    # ── NEW: PATTERN 2: Standalone Pack Size (Rule 4) ──
    # If the quantity cell contains ONLY a pack-like pattern, do not parse it as quantity (return 0).
    # Examples: "1*10" -> billed_qty=0, "200ML" -> billed_qty=0
    is_pack_alone = False
    if text.upper() == "MIS":
        is_pack_alone = True
    elif re.fullmatch(r"\d+\s*(?:GM|ML|MG|TAB|CAP|S|'S|NOS)", text, re.IGNORECASE):
        is_pack_alone = True
    elif re.fullmatch(r"1\s*[\*\-xX×/:=]\s*\d+", text, re.IGNORECASE):
        is_pack_alone = True
        
    if is_pack_alone:
        pack_sz = None
        mult_match = re.search(r"(\d+)[\*\-xX×/:=](\d+)", text)
        if mult_match:
            try:
                p1 = int(mult_match.group(1))
                p2 = int(mult_match.group(2))
                pack_sz = p1 * p2
            except ValueError:
                pass
        if pack_sz is None:
            unit_match = re.search(r"\b(\d+)\s*(?:GM|ML|MG|TAB|CAP|S|'S|NOS)", text, re.IGNORECASE)
            if unit_match:
                try:
                    pack_sz = int(unit_match.group(1))
                except ValueError:
                    pass

        logger.info(f"qty_parser: standalone pack size detected '{original}' -> returning 0 quantity")
        return ParsedQuantity(
            billed_qty=Decimal("0"),
            free_qty=Decimal("0"),
            total_qty=Decimal("0"),
            pack_size=pack_sz,
            is_scheme=False,
            raw=original,
            parse_method="pack_size_alone",
            qty_parse_rejected_reason="pack_size_alone",
        )

    # ── PATTERN 4: Parenthesized pack ──
    paren_re = re.compile(
        r'^(\d+\.?\d*)\s*'
        r'\(([^)]+)\)$'
    )
    m = paren_re.match(text)
    if m:
        try:
            outer_qty = _safe_decimal(m.group(1))
            inner_expr = m.group(2)
            inner_parts = inner_expr.split("*")
            inner_product = Decimal("1")
            for part in inner_parts:
                inner_product *= _safe_decimal(part)
            total = outer_qty * inner_product
            pack_sz = int(inner_product)
            return ParsedQuantity(
                billed_qty=total,
                free_qty=Decimal("0"),
                total_qty=total,
                pack_size=pack_sz,
                is_scheme=False,
                raw=original,
                parse_method="parenthesized_pack",
            )
        except (InvalidOperation, ValueError):
            logger.warning(
                f"qty_parser: parenthesized pack parse failed for '{original}'"
            )

    # ── PATTERN 3: Scheme notation (billed + free) ──
    parse_text, extracted_expression, rejected_reason = _extract_quantity_expression(text)
    scheme_re = re.compile(
        r'^(\d*\.?\d+)\+(\d*\.?\d+)$'
    )
    m = scheme_re.match(parse_text)
    if m:
        try:
            billed = _safe_decimal(m.group(1))
            free = _safe_decimal(m.group(2))
            return ParsedQuantity(
                billed_qty=billed,
                free_qty=free,
                total_qty=billed + free,
                is_scheme=True,
                raw=original,
                parse_method="scheme_notation_extracted" if extracted_expression else "scheme_notation",
                qty_parse_extracted_expression=extracted_expression,
            )
        except InvalidOperation:
            logger.warning(f"qty_parser: scheme parse failed for '{original}'")

    # ── PATTERN 5: Multiply/pack notation ──
    if "*" in parse_text:
        parts = parse_text.split("*")
        if all(re.match(r'^\d+\.?\d*$', p.strip()) for p in parts):
            try:
                product = Decimal("1")
                for p in parts:
                    product *= _safe_decimal(p)
                pack_sz = int(product)
                return ParsedQuantity(
                    billed_qty=product,
                    free_qty=Decimal("0"),
                    total_qty=product,
                    pack_size=pack_sz,
                    is_scheme=False,
                    raw=original,
                    parse_method="pack_multiply_extracted" if extracted_expression else "pack_multiply",
                    qty_parse_extracted_expression=extracted_expression,
                )
            except (InvalidOperation, ValueError):
                logger.warning(
                    f"qty_parser: pack multiply parse failed for '{original}'"
                )

    # ── PATTERN 6: Plain numeric ──
    plain_re = re.compile(
        r'^(\d+\.?\d*)$'
    )
    m = plain_re.match(parse_text)
    if m:
        try:
            val = _safe_decimal(m.group(1))
            return ParsedQuantity(
                billed_qty=val,
                free_qty=Decimal("0"),
                total_qty=val,
                is_scheme=False,
                raw=original,
                parse_method="plain_numeric_extracted" if extracted_expression else "plain_numeric",
                qty_parse_extracted_expression=extracted_expression,
            )
        except InvalidOperation:
            pass

    # ── FALLBACK: Unparseable ──
    logger.warning(
        f"qty_parser: could not parse quantity '{original}' "
        f"reason={rejected_reason or 'unparsed_quantity_expression'}"
    )
    return ParsedQuantity(
        raw=original,
        parse_method="unparsed",
        qty_parse_extracted_expression=extracted_expression,
        qty_parse_rejected_reason=rejected_reason or "unparsed_quantity_expression",
    )


def is_compound_quantity(text: str) -> bool:
    """Quick check if a text value looks like a compound quantity format."""
    if not text:
        return False
    cleaned = _normalize_ocr_noise(text)
    parse_text, extracted_expression, _ = _extract_quantity_expression(cleaned)
    if extracted_expression:
        return True
    if re.match(r'^\d*\.?\d+\+\d*\.?\d+$', parse_text):
        return True
    if re.match(r'^\d+\.?\d*(\*\d+\.?\d*)+$', parse_text):
        return True
    if re.match(r'^\d+\.?\d*\s*\([^)]+\)$', parse_text):
        return True
    return False


# ── Doctest / Test Cases Runner ──
if __name__ == "__main__":
    import doctest
    results = doctest.testmod(verbose=True)

    # Manual test cases covering OCR noise and edge cases
    test_cases = [
        # (input, expected_billed, expected_free, expected_scheme)
        ("2.750+.250", Decimal("2.750"), Decimal("0.250"), True),
        ("4.50+.50", Decimal("4.50"), Decimal("0.50"), True),
        ("2+1", Decimal("2"), Decimal("1"), True),
        # New Rule 4: Standalone pack size alone does not become quantity
        ("1*15", Decimal("0"), Decimal("0"), False),
        ("1*10", Decimal("0"), Decimal("0"), False),
        ("200ML", Decimal("0"), Decimal("0"), False),
        ("15GM", Decimal("0"), Decimal("0"), False),
        ("MIS", Decimal("0"), Decimal("0"), False),
        # Nested compound quantities still parse
        ("3*1*15", Decimal("45"), Decimal("0"), False),
        ("2 (1*10)", Decimal("20"), Decimal("0"), False),
        ("2", Decimal("2"), Decimal("0"), False),
        ("1.84", Decimal("1.84"), Decimal("0"), False),
        # New Rule 2: Fused Qty/Pack parses trailing standalone integer
        ("1*10 2", Decimal("2"), Decimal("0"), False),
        ("1-10 2", Decimal("2"), Decimal("0"), False),
        ("MIS 3", Decimal("3"), Decimal("0"), False),
        ("1:10= 2", Decimal("2"), Decimal("0"), False),
        # OCR noise variants
        ("2,750+,250", Decimal("2.750"), Decimal("0.250"), True),
        ("2.750 +.250", Decimal("2.750"), Decimal("0.250"), True),
        ("2.750+0.250", Decimal("2.750"), Decimal("0.250"), True),
        # Multiplication symbol variants
        ("3×1×15", Decimal("45"), Decimal("0"), False),
        ("3x1x15", Decimal("45"), Decimal("0"), False),
    ]

    print("\n--- Manual Test Cases ---")
    all_pass = True
    for raw_input, exp_billed, exp_free, exp_scheme in test_cases:
        r = parse_quantity(raw_input)
        ok = (
            r.billed_qty == exp_billed
            and r.free_qty == exp_free
            and r.is_scheme == exp_scheme
        )
        status = "✓" if ok else "✗"
        if not ok:
            all_pass = False
        print(
            f"  {status} parse_quantity('{raw_input}') → "
            f"billed={r.billed_qty}, free={r.free_qty}, "
            f"scheme={r.is_scheme}, method={r.parse_method}, pack_size={r.pack_size}"
        )

    compound_tests = [
        ("2.750+.250", True),
        ("3*1*15", True),
        ("2 (1*10)", True),
        ("1.84", False),
        ("2", False),
        ("hello", False),
    ]
    print("\n--- is_compound_quantity Tests ---")
    for text, expected in compound_tests:
        result = is_compound_quantity(text)
        ok = result == expected
        status = "✓" if ok else "✗"
        if not ok:
            all_pass = False
        print(f"  {status} is_compound_quantity('{text}') → {result}")

    print(f"\n{'All tests passed!' if all_pass else 'SOME TESTS FAILED!'}")
