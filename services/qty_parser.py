"""
Quantity Parser for Indian Pharmaceutical Invoice Formats.

Handles compound, scheme, and pack quantity notations commonly found in
Indian pharma distributor invoices. Normalizes all formats into a structured
ParsedQuantity model with billed/free/total decomposition.

Supported formats:
    "2.750+.250"    → 2.75 billed + 0.25 free (scheme notation)
    "4.50+.50"      → 4.5 billed + 0.5 free
    "2+1"           → 2 billed + 1 free (integer scheme)
    "1*15"          → 15 total (pack: 1 box × 15 strips)
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
from typing import Optional
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


def parse_quantity(raw: str) -> ParsedQuantity:
    """Parse an Indian pharma quantity string into structured components.

    Processes the raw string through a prioritized regex pipeline:
    1. Scheme notation: billed+free (e.g., "2.750+.250")
    2. Parenthesized pack: qty (pack_expr) (e.g., "2 (1×10)")
    3. Pack/multiply notation: a*b*c (e.g., "3×1×15")
    4. Plain numeric: integer or decimal (e.g., "2", "1.84")

    Args:
        raw: Raw text from a quantity cell in an OCR-extracted invoice table.

    Returns:
        ParsedQuantity with billed_qty, free_qty, total_qty, etc.

    Raises:
        No exceptions raised — returns a zero-quantity result on parse failure
        and logs a warning.

    Examples:
        >>> r = parse_quantity("2.750+.250")
        >>> (r.billed_qty, r.free_qty, r.is_scheme)
        (Decimal('2.750'), Decimal('0.250'), True)

        >>> r = parse_quantity("2+1")
        >>> (r.billed_qty, r.free_qty, r.total_qty)
        (Decimal('2'), Decimal('1'), Decimal('3'))

        >>> r = parse_quantity("3*1*15")
        >>> (r.total_qty, r.pack_size, r.is_scheme)
        (Decimal('45'), 45, False)

        >>> r = parse_quantity("2 (1*10)")
        >>> (r.total_qty, r.pack_size)
        (Decimal('20'), 10)

        >>> r = parse_quantity("1.84")
        >>> (r.billed_qty, r.is_scheme)
        (Decimal('1.84'), False)
    """
    if not raw or not raw.strip():
        return ParsedQuantity(raw=raw or "", parse_method="empty")

    text = _normalize_ocr_noise(raw)
    original = raw.strip()

    # ── PATTERN 1: Scheme notation (billed + free) ──
    # Matches: "2.750+.250", "4.50+0.50", "2+1", ".750+.250"
    # Regex: one or more digit/dot groups separated by '+'
    scheme_re = re.compile(
        r'^(\d*\.?\d+)\+(\d*\.?\d+)$'  # group1 + group2, both numeric
    )
    m = scheme_re.match(text)
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
                parse_method="scheme_notation",
            )
        except InvalidOperation:
            logger.warning(f"qty_parser: scheme parse failed for '{original}'")

    # ── PATTERN 2: Parenthesized pack — "2 (1*10)" or "2(1×10)" ──
    # Outer qty × inner pack expression
    paren_re = re.compile(
        r'^(\d+\.?\d*)\s*'   # outer quantity (e.g., "2")
        r'\(([^)]+)\)$'      # parenthesized inner expression (e.g., "1*10")
    )
    m = paren_re.match(text)
    if m:
        try:
            outer_qty = _safe_decimal(m.group(1))
            inner_expr = m.group(2)
            # Evaluate inner pack expression: "1*10" → 10
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

    # ── PATTERN 3: Multiply/pack notation — "1*15", "3*1*15" ──
    # All components multiplied together to get total dispatched units
    if "*" in text:
        parts = text.split("*")
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
                    parse_method="pack_multiply",
                )
            except (InvalidOperation, ValueError):
                logger.warning(
                    f"qty_parser: pack multiply parse failed for '{original}'"
                )

    # ── PATTERN 4: Plain numeric — "2", "1.84", "2.00" ──
    # Standard integer or decimal quantity
    plain_re = re.compile(
        r'^(\d+\.?\d*)$'  # one numeric group, optional decimal
    )
    m = plain_re.match(text)
    if m:
        try:
            val = _safe_decimal(m.group(1))
            return ParsedQuantity(
                billed_qty=val,
                free_qty=Decimal("0"),
                total_qty=val,
                is_scheme=False,
                raw=original,
                parse_method="plain_numeric",
            )
        except InvalidOperation:
            pass

    # ── FALLBACK: Unparseable ──
    logger.warning(f"qty_parser: could not parse quantity '{original}'")
    return ParsedQuantity(raw=original, parse_method="unparsed")


def is_compound_quantity(text: str) -> bool:
    """Quick check if a text value looks like a compound quantity format.

    Used by ioa_mapping.py collision detection to suppress false alerts
    on multi-number cells that are actually scheme/pack quantities.

    Args:
        text: Cell text to check.

    Returns:
        True if the text matches scheme ("+") or pack ("*"/"×") notation.
    """
    if not text:
        return False
    cleaned = _normalize_ocr_noise(text)
    # Scheme: digits+digits
    if re.match(r'^\d*\.?\d+\+\d*\.?\d+$', cleaned):
        return True
    # Pack: digits*digits (with optional additional *digits)
    if re.match(r'^\d+\.?\d*(\*\d+\.?\d*)+$', cleaned):
        return True
    # Parenthesized: digits (expr)
    if re.match(r'^\d+\.?\d*\s*\([^)]+\)$', cleaned):
        return True
    return False


# ── Doctest Runner ──
if __name__ == "__main__":
    import doctest
    results = doctest.testmod(verbose=True)

    # Additional manual test cases covering OCR noise and edge cases
    test_cases = [
        # (input, expected_billed, expected_free, expected_scheme)
        ("2.750+.250", Decimal("2.750"), Decimal("0.250"), True),
        ("4.50+.50", Decimal("4.50"), Decimal("0.50"), True),
        ("2+1", Decimal("2"), Decimal("1"), True),
        ("1*15", Decimal("15"), Decimal("0"), False),
        ("3*1*15", Decimal("45"), Decimal("0"), False),
        ("2 (1*10)", Decimal("20"), Decimal("0"), False),
        ("2", Decimal("2"), Decimal("0"), False),
        ("1.84", Decimal("1.84"), Decimal("0"), False),
        # OCR noise variants
        ("2,750+,250", Decimal("2.750"), Decimal("0.250"), True),
        ("2.750 +.250", Decimal("2.750"), Decimal("0.250"), True),
        ("2.750+0.250", Decimal("2.750"), Decimal("0.250"), True),
        # Multiplication symbol variants
        ("3×1×15", Decimal("45"), Decimal("0"), False),
        ("3x1x15", Decimal("45"), Decimal("0"), False),
        # is_compound_quantity checks
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
            f"scheme={r.is_scheme}, method={r.parse_method}"
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
