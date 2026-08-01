import math
import re
from typing import Any, Dict, List, Optional
from extraction.normalizers.canonical_invoice import CanonicalInvoice, CanonicalLineItem
from extraction.normalizers.amount_inference import fill_missing_amounts

def _row_reading_order_key(bbox: List[float], angle_rad: float) -> float:
    """
    Returns a sort key that increases in true top-to-bottom reading order,
    regardless of page rotation. bbox is [min_x, min_y, max_x, max_y] in the
    raw (unrotated) image's normalized coordinate frame - the same frame the
    stored bounding_box uses for on-image overlay, so this only affects the
    sort, never the stored coordinates. Rotating the bbox center by the page
    angle projects it onto the axis that is "down the printed page": at 0
    degrees that's just y; at ~90 degrees (a sideways photo) it's -x.
    """
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    return -center_x * math.sin(angle_rad) + center_y * math.cos(angle_rad)

def is_numeric(s: str) -> bool:
    """Checks if a stripped string is a valid integer or float."""
    # Remove a single decimal point and check if the remainder is digits
    return s.replace(".", "", 1).isdigit()

def clean_decimal_string(val: str) -> str:
    """
    Cleans up numeric strings from OCR and formatting variations:
    - Removes currency symbols ($, ₹).
    - Converts spaces between numbers (e.g. "52 53") to a dot (e.g. "52.53").
    - Handles commas: if a comma is followed by exactly two digits at the end of the string
      (e.g., "126,99"), treats the last comma as a decimal separator and replaces it with a dot,
      while removing any other commas. Otherwise, removes all commas as thousands separators.
    """
    s = val.strip()
    # Strip leading noise characters: |, :, ;, space
    while s and s[0] in ['|', ':', ';', ' ']:
        s = s[1:].strip()
    # Remove common currency symbols
    s = s.replace("$", "").replace("₹", "")
    
    # Check for space as dot separator (e.g., "52 53" -> "52.53")
    if re.match(r'^\d+ +\d+$', s):
        s = re.sub(r' +', '.', s)
        return s
        
    # Remove all other whitespace
    s = s.replace(" ", "")

    if "," in s:
        # Check if the last comma is followed by exactly two digits at the end
        if re.search(r',\d{2}$', s):
            r_idx = s.rfind(",")
            # Replace the last comma with a dot and remove all other commas
            s = s[:r_idx].replace(",", "") + "." + s[r_idx+1:]
        else:
            # Just remove commas as thousands separators (e.g., "1,269.90" -> "1269.90")
            s = s.replace(",", "")
            
    return s

def parse_decimal_safe(value: Any) -> Any:
    """
    Safely parses input to float or int after cleaning it.
    If parsing fails, returns the original stripped string.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        clean = clean_decimal_string(s)
        if "." in clean:
            return float(clean)
        return int(clean)
    except ValueError:
        return s

def try_parse_float(val: Any) -> Optional[float]:
    """Attempts to parse a float value, returning None if parsing fails."""
    if val is None:
        return None
    try:
        clean = clean_decimal_string(str(val))
        return float(clean)
    except ValueError:
        return None

# Expiry values on Indian pharma invoices are always digits with a "/" (or
# occasionally "-"/".") separator, e.g. "8/27" or "07-27" - never letters.
# Azure's OCR sometimes misreads a digit as the visually closest letter
# (e.g. "8" -> "B"); since letters are never valid here, map the common
# confusions back to their digit rather than leaving/dropping them.
_EXPIRY_OCR_DIGIT_MAP = {
    "O": "0", "o": "0", "D": "0", "Q": "0",
    "I": "1", "i": "1", "l": "1", "L": "1", "|": "1",
    "Z": "2", "z": "2",
    "S": "5", "s": "5",
    "G": "6",
    "T": "7",
    "B": "8",
    "g": "9", "q": "9",
}

def clean_expiry_string(value: Any) -> Optional[str]:
    """
    Normalizes OCR'd expiry values. Expiry fields only ever contain digits
    and a separator, so any letter is necessarily an OCR misread - map
    known digit/letter lookalikes back to the digit, and drop anything else
    unrecognized (stray punctuation/whitespace noise from OCR).
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    # A cell holding several lines has picked up more than one item's expiry
    # (Azure merges vertically adjacent cells when a column is typeset off the
    # row grid). Concatenating them yields nonsense like "4/281/28", so keep
    # the first line - the one belonging to this row.
    lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
    if len(lines) > 1:
        s = lines[0]

    fixed_chars = []
    for ch in s:
        if ch.isdigit() or ch in "/-.":
            fixed_chars.append(ch)
        elif ch in _EXPIRY_OCR_DIGIT_MAP:
            fixed_chars.append(_EXPIRY_OCR_DIGIT_MAP[ch])
        # else: unrecognized character in an expiry field - drop it.

    result = "".join(fixed_chars)
    return result if result else None

def parse_split_quantity(value: Any) -> Optional[Dict[str, float]]:
    """
    Parses same-cell billed/free quantity expressions such as "2.75 + .25".
    Only accepts an explicit plus sign between two numeric values.
    """
    if value is None:
        return None

    text = str(value).strip()
    if not text or "+" not in text:
        return None

    normalized = re.sub(r'\s+', ' ', text)
    number_pattern = r'(?:\d+(?:[.,]\d+)?|[.,]\d+)'
    match = re.match(
        rf'^[^\d.,]*({number_pattern})\s*\+\s*({number_pattern})[^\d.,]*$',
        normalized
    )
    if not match:
        return None

    billed_qty = try_parse_float(match.group(1))
    free_qty = try_parse_float(match.group(2))
    if billed_qty is None or free_qty is None:
        return None

    return {
        "quantity": billed_qty,
        "free_quantity": free_qty,
    }

def is_discount_label(label: str) -> bool:
    """Detects footer/header discount aliases without treating unrelated text as discount."""
    normalized = re.sub(r'[^a-z0-9]+', ' ', label.lower()).strip()
    aliases = {
        "dis amt",
        "disc amt",
        "discount",
        "discount amt",
        "scheme discount",
        "sch discount",
        "oth disc amt",
    }
    if normalized in aliases:
        return True
    return "discount" in normalized or normalized.startswith("disc ") or normalized.startswith("dis ")

_SUBTOTAL_LABELS = [
    "sub total", "subtotal", "taxable amount", "taxable value", "taxable total",
    "net taxable", "gross total", "gross amount", "amount before tax",
    "total before tax", "basic amount", "basic value", "item total",
]
_GRAND_TOTAL_LABELS = [
    "grand total", "net total", "payable amount", "total payable", "net amt",
    "net amount", "bill amount",
]

def _is_footer_label(text: str) -> bool:
    """Whether a cell reads like a totals-block label rather than a value."""
    t = text.lower().strip()
    if not t:
        return False
    if any(k in t for k in _SUBTOTAL_LABELS) or any(k in t for k in _GRAND_TOTAL_LABELS):
        return True
    if is_discount_label(t):
        return True
    return any(k in t for k in ("sgst", "cgst", "igst", "round", "total"))


def _footer_label_and_value(row: List[str]) -> "tuple[Optional[str], Optional[str]]":
    """Finds a totals row's label and its amount.

    Locates the cell that actually reads like a label and takes the next
    non-empty cell as its value, rather than assuming the pair occupies the
    first two populated columns. Real footers put stray text beside the
    figures - the amount-in-words line often shares a row with "Round Off",
    which would otherwise be read as that row's value.
    """
    for idx, cell in enumerate(row):
        text = (cell or "").strip()
        if text and _is_footer_label(text):
            for nxt in row[idx + 1:]:
                if nxt and nxt.strip():
                    return text, nxt.strip()
            return text, None
    return _first_two_nonempty(row)


def _first_two_nonempty(row: List[str]) -> "tuple[Optional[str], Optional[str]]":
    """Returns (label, value) as the first two non-empty cells in row, in
    that order. Most footer tables put the label in column 0 and the value
    in column 1, but some invoices leave a leading blank column (a stray
    merged/empty cell from the original layout), shifting the real pair one
    or more columns to the right - scanning left-to-right for content
    handles both without needing to special-case the shifted layout."""
    nonempty = [c for c in row if c and c.strip()]
    lbl = nonempty[0] if len(nonempty) > 0 else None
    val = nonempty[1] if len(nonempty) > 1 else None
    return lbl, val

# Canonical spellings for each column concept, in one table rather than
# scattered through an if/elif chain. This is the single source of truth for
# both exact matching and the OCR-tolerant fallback built from it below.
_HEADER_LABELS: Dict[str, List[str]] = {
    "serial": ["51", "sl", "s1", "sr", "s.no", "s", "s.", "sr.", "sl."],
    "product_code": ["pchde", "pcode", "product code", "item code"],
    "product": [
        "product", "particulars", "item", "description", "product name",
        "item name", "tiem description", "product description", "item description",
    ],
    "pack": ["ufc", "uom", "unit", "pack", "packing", "pkg"],
    "quantity_total": ["total 0y", "total qy", "total qty"],
    "quantity_tes": ["t'es"],
    "quantity_pcs": [
        "qty", "qty.", "quantity", "quant", "pes", "pcs", "pieces",
        "bill qty", "billed qty", "sale qty", "sold qty",
    ],
    "free_quantity": [
        "free", "free qty", "free quantity", "free.qty", "free.quantity",
        "f.qty", "f qty", "scheme qty", "sch qty", "bonus qty", "fr", "foc",
    ],
    "batch": ["batch", "batch no", "batch no.", "batchno", "b.no", "b.no."],
    "expiry": [
        "exp", "expiry", "exp.", "exp date", "exp.date", "expiry date",
        "exp dt", "exp.dt", "exp dt.", "expdt", "exp dt/mfg dt",
    ],
    "hsn": ["hsn", "hsn code", "hsncode", "hsn/sac"],
    "mrp": ["mrp", "m.r.p.", "m.r.p"],
    "rate": ["rate", "unit rate", "price", "unit price"],
    "gross_amount": ["grass amt", "gross amt", "gross_amt", "grossamt"],
    "sch_amt": ["sch amt"],
    "dise_amt": ["dise amt"],
    # A discount column is either a percentage or a rupee amount, and the two
    # must not share a concept: subtracting "2.00" when it means 2% silently
    # mis-prices the line. Where the header says which, it is mapped
    # accordingly; a bare "Dis"/"Discount" stays on the amount field, and the
    # per-invoice amount formula inference works out what it really is.
    "discount_percent": ["disc %", "discount %", "dis %", "disc%", "dis%", "d%"],
    "discount": [
        "dis", "dis.", "disc", "disc.", "dise", "discount",
        "dis amt", "disc amt", "discount amt",
        "scheme discount", "sch discount", "oth disc amt", "disc.amt other disc",
    ],
    "gst_percent": ["ott %", "gst %", "tax %", "gst%", "tax%"],
    "cgst_amount": ["howwy ciget", "cgst amt", "ciget amt", "cgst amount"],
    "sgst_amount": ["øget amt", "oget amt", "sgst amt", "sgst amount"],
    "amount": [
        "net amt", "net amount", "amount", "amt", "amt.", "value", "total",
        "total amount",
    ],
    "taxable_amount": ["taxable amt", "trashle amt", "taxable amount"],
    # The invoice's own precomputed tax for this row (e.g. "Tot.Tax") - summed
    # across items as an invoice-level tax fallback, in preference to
    # re-deriving tax from rate/GST% math ourselves.
    "line_tax_amount": ["tot.tax", "tot tax", "total tax", "tax amt", "tax amount"],
}

_EXACT_HEADER_MAP: Dict[str, str] = {
    label: concept for concept, labels in _HEADER_LABELS.items() for label in labels
}

# Characters OCR routinely swaps for one another, grouped by what they look
# like. Collapsing each group to one representative lets a misread header
# still match: "QTY." read as "OTY." differs only by Q/O.
#
# Only visually confusable characters are grouped, which is what keeps the
# tax columns safe - s, c and i look nothing alike, so "sgst", "cgst" and
# "igst" stay distinct under this mapping. A test asserts that no two
# different concepts collapse to the same key.
_OCR_VISUAL_GROUPS = {
    "0": "oq0d",
    "1": "il1|",
    "5": "s5",
    "8": "b8",
    "6": "g6",
    "2": "z2",
    "7": "t7",
}
_VISUAL_CHAR_MAP = {
    ch: representative
    for representative, chars in _OCR_VISUAL_GROUPS.items()
    for ch in chars
}

def ocr_visual_key(text: str) -> str:
    """Collapses a header to an OCR-tolerant key: lowercased, stripped of
    punctuation and spacing, with look-alike characters unified."""
    compact = re.sub(r'[^a-z0-9%]', '', text.lower())
    return "".join(_VISUAL_CHAR_MAP.get(ch, ch) for ch in compact)


def _build_visual_header_map() -> Dict[str, str]:
    """Visual key -> concept, excluding any key two concepts share.

    An ambiguous key is dropped rather than resolved arbitrarily: mapping a
    column to the wrong concept silently corrupts every row, while dropping
    it just leaves the column unmapped as it is today.
    """
    keyed: Dict[str, set] = {}
    for label, concept in _EXACT_HEADER_MAP.items():
        keyed.setdefault(ocr_visual_key(label), set()).add(concept)
    return {key: next(iter(concepts)) for key, concepts in keyed.items() if len(concepts) == 1 and key}


_VISUAL_HEADER_MAP: Dict[str, str] = _build_visual_header_map()


def normalize_header(header_text: str, allow_substring: bool = True) -> Optional[str]:
    """
    Normalizes Azure table header text to canonical column keys.
    Maps variations of common columns used in pharma invoices, supporting typos.

    Resolution order: exact match, then the sgst/cgst/igst substring rules,
    then an OCR-tolerant match that forgives look-alike character swaps.

    allow_substring gates the sgst/cgst/igst "in t" checks below. Those are
    safe on a genuine single-concept header (e.g. "CGST Amt"), but unsafe on
    a header cell that stacks two unrelated concepts on separate lines (e.g.
    "MRP\nCGST %" collapses to "mrp cgst %", which contains "cgst" purely by
    coincidence - the column is really MRP on one physical row and CGST% on
    another). Callers checking a whole multi-line cell as one string should
    pass allow_substring=False; per-line checks can leave it at the default.
    """
    t = header_text.lower().strip()
    # Normalize multiple whitespaces to single space
    t = re.sub(r'\s+', ' ', t)

    concept = _EXACT_HEADER_MAP.get(t)
    if concept:
        return concept

    if allow_substring:
        if "sgst" in t:
            if "amt" in t or "amount" in t:
                return "sgst_amount"
            return "sgst_percent"
        if "cgst" in t:
            if "amt" in t or "amount" in t or "ciget" in t:
                return "cgst_amount"
            return "cgst_percent"
        if "igst" in t:
            if "amt" in t or "amount" in t:
                return "igst_amount"
            return "igst_percent"

    # OCR-tolerant fallback. Every header list above started as an exact
    # string, and each new invoice layout kept adding one more misread
    # spelling ("OTY." for "QTY.", "GrossAmt" for "Gross Amt"). Matching on
    # the look-alike-collapsed form absorbs that whole class instead.
    return _VISUAL_HEADER_MAP.get(ocr_visual_key(t))

def normalize_header_row(header_row: List[str]) -> List[Optional[str]]:
    """
    Normalizes a complete row of table headers, handling duplicate columns
    like 'Value' in a context-aware way and cleaning up noise.
    """
    cleaned_full = []
    for cell in header_row:
        # Replace all whitespaces/newlines with single space
        full = re.sub(r'\s+', ' ', cell.lower().strip())
        cleaned_full.append(full)
        
    # Determine if there is any free quantity column
    has_free_column = False
    for cell in header_row:
        full = re.sub(r'\s+', ' ', cell.lower().strip())
        norm = normalize_header(full)
        if norm == "free_quantity":
            has_free_column = True
            break
            
    # Determine if there is any explicit amount column
    has_explicit_amount = False
    for cell in header_row:
        full = re.sub(r'\s+', ' ', cell.lower().strip())
        if full != "value":
            norm = normalize_header(full)
            if norm == "amount":
                has_explicit_amount = True
                break
                
    col_names = []
    for i, cell in enumerate(header_row):
        t = cleaned_full[i]
        
        # 1. Batch header cleanup (also matches "Hatch", a common OCR misread of "Batch")
        if "batch" in t or t.startswith("batch") or t.startswith("b.no") or "b.no" in t or t == "hatch":
            col_names.append("batch")
            continue
            
        # 1.5 Total Qty conditional mapping
        if t in ["total qty", "total qty.", "total quantity"]:
            if has_free_column:
                col_names.append("quantity_total")
            else:
                col_names.append("quantity_pcs")
            continue
            
        # 2. Context-aware Value mapping
        if t == "value":
            mapped = None
            if i > 0:
                prev_t = cleaned_full[i-1]
                if "sgst" in prev_t:
                    mapped = "sgst_amount"
                elif "cgst" in prev_t:
                    mapped = "cgst_amount"
                elif "igst" in prev_t:
                    mapped = "igst_amount"
                elif any(term in prev_t for term in ["gst", "tax", "dis", "discount"]):
                    mapped = None
                    
            if mapped is None:
                if not has_explicit_amount:
                    mapped = "amount"
            col_names.append(mapped)
            continue
            
        # 3. Standard normalization using full cell content. A multi-line
        # cell might stack two unrelated concepts (see normalize_header's
        # allow_substring docstring) - the substring-based gst checks are
        # only trustworthy on a genuine single-line header.
        norm = normalize_header(cell, allow_substring=("\n" not in cell))
        col_names.append(norm)

    # 4. Positional fallback for a garbled Qty header (e.g. OCR mangles "Qty"
    # into something like "(1)"). On Indian pharma invoices the Qty column is
    # reliably immediately left of MRP; if that slot has real (non-empty) but
    # unrecognized header text and no quantity column was already found
    # elsewhere, treat it as quantity.
    qty_keys = {"quantity", "quantity_pcs", "quantity_total", "quantity_tes"}
    if not any(name in qty_keys for name in col_names):
        try:
            mrp_idx = col_names.index("mrp")
        except ValueError:
            mrp_idx = -1
        if mrp_idx > 0 and col_names[mrp_idx - 1] is None and cleaned_full[mrp_idx - 1].strip():
            col_names[mrp_idx - 1] = "quantity_pcs"

    return col_names

def extract_corrected_qty(qty_text: Optional[str], serial_text: Optional[str]) -> Optional[Any]:
    """
    Corrects issues where quantity and serial are merged or misaligned.
    - If qty has multiple lines, use the last numeric line.
    - If qty is empty but serial has multiple lines, use the last numeric line as qty.
    - Does not treat single-line serial numbers alone as quantity.
    """
    qty_str = qty_text.strip() if qty_text else ""
    serial_str = serial_text.strip() if serial_text else ""
    
    if qty_str:
        lines = [l.strip() for l in qty_str.split("\n") if l.strip()]
        if len(lines) > 1:
            for line in reversed(lines):
                clean = line.replace(",", "").replace(" ", "")
                if is_numeric(clean):
                    return parse_decimal_safe(clean)
            # Fallback to the whole string if no line was numeric
            return qty_str
        return parse_decimal_safe(qty_str)
        
    if serial_str:
        lines = [l.strip() for l in serial_str.split("\n") if l.strip()]
        if len(lines) > 1:
            for line in reversed(lines):
                clean = line.replace(",", "").replace(" ", "")
                if is_numeric(clean):
                    return parse_decimal_safe(clean)

    return None

# A handwritten tick beside the quantity is normal on these invoices, and OCR
# renders it as a stray leading character - "v1", "L2", "+1", "-3", "₩1".
# Where exactly one number survives after that junk, it is the quantity.
_SINGLE_NUMBER_RE = re.compile(r'\d+(?:\.\d+)?')

def salvage_tick_marked_qty(qty_text: Optional[str]) -> Optional[float]:
    """Recovers a quantity written next to a handwritten tick.

    Two cases, both deliberately narrow:

    1. The cell still holds exactly one number ("v1", "L2", "-3") - use it.
       More than one number is ambiguous and yields nothing.
    2. The cell holds no digit at all ("VI", "NI", "LI"): the tick AND the
       digit both came back as letters. Dropping the leading tick character
       and mapping the remainder through the digit look-alike table recovers
       it. Anything that does not map cleanly to digits ("VA") stays blank.

    Blank is the safe failure here - the reviewer sees an amber "missing"
    flag rather than a plausible but invented stock quantity.
    """
    if not qty_text:
        return None
    text = str(qty_text).strip()
    if not text:
        return None

    numbers = _SINGLE_NUMBER_RE.findall(text)
    if numbers:
        if len(numbers) != 1:
            return None
        try:
            return float(numbers[0])
        except ValueError:
            return None

    # No digits at all: treat the first character as the tick mark and read
    # what follows as digits rendered as letters.
    remainder = text[1:].strip()
    if not remainder or len(remainder) > 2:
        return None
    mapped = "".join(_EXPIRY_OCR_DIGIT_MAP.get(ch, "") for ch in remainder)
    if len(mapped) != len(remainder) or not mapped.isdigit():
        return None
    try:
        return float(mapped)
    except ValueError:
        return None

def extract_gst_percent(sgst_raw: Any, cgst_raw: Any, igst_raw: Any) -> Optional[float]:
    """Combines SGST and CGST percentages, or falls back to IGST percent.

    An intra-state supply under Indian GST is always split into equal CGST and
    SGST halves - across every invoice processed here, 78 rows carried both and
    all 78 were equal, with none differing. So a lone half implies the other
    and the rate is double it.

    That matters because these cells do go missing: on a real invoice the CGST
    value was merged into the neighbouring C.D. column ("9.0015.20 %"), leaving
    the CGST cell empty. Requiring both halves made those lines read 0% instead
    of 18%, which then flowed into inventory as tax-free stock.
    """
    sgst_val = try_parse_float(sgst_raw)
    cgst_val = try_parse_float(cgst_raw)
    igst_val = try_parse_float(igst_raw)

    if sgst_val is not None and cgst_val is not None:
        # One half read as zero while the other is non-zero is not a valid
        # split - it is a half that failed to read - so infer from the
        # non-zero one rather than reporting half the true rate.
        if sgst_val == 0 and cgst_val > 0:
            return cgst_val * 2
        if cgst_val == 0 and sgst_val > 0:
            return sgst_val * 2
        return sgst_val + cgst_val
    if sgst_val is not None:
        return sgst_val * 2
    if cgst_val is not None:
        return cgst_val * 2
    if igst_val is not None:
        return igst_val
    return None

def score_footer_table(grid: List[List[str]]) -> int:
    """
    Scores a grid based on matches with common invoice footer/totals labels.
    Helps locate the totals section of the invoice.
    """
    score = 0
    footer_keys = [
        "sub total", "subtotal", "grand total", "discount", "disc amt", "dis amt",
        "sgst", "cgst", "igst", "roundoff", "round off", "net amt", "net payable", "payable amount",
    ]
    for row in grid:
        # Label and value aren't always in columns 0/1 - some invoices leave
        # a blank leading column, shifting the real pair rightward.
        lbl, val = _first_two_nonempty(row)
        if lbl and val and (any(k in lbl.lower() for k in footer_keys) or is_discount_label(lbl.lower())):
            score += 1
    return score

def parse_horizontal_summary_table(grid: List[List[str]]) -> Optional[Dict[str, float]]:
    """
    Parses horizontal totals summary grids (like CM Associates TABLE 2)
    where particulars, gross, discount, taxes, net are column headers.
    Locates the Total row and yields normalized totals.
    """
    if not grid or len(grid) < 2:
        return None
        
    # Scan for a header row containing at least two core totals columns
    header_idx = None
    target_terms = {"particulars", "gros ami", "gross amt", "sch amt", "dis amt", "disc amt", "oth disc amt", "discount", "trashle amt", "taxable amt", "net amt", "net payable"}
    
    for r_idx, row in enumerate(grid):
        match_count = 0
        for cell in row:
            c = cell.lower().strip()
            if any(term in c for term in target_terms):
                match_count += 1
        if match_count >= 2:
            header_idx = r_idx
            break
            
    if header_idx is None:
        return None
        
    # Locate the Total row underneath
    total_row_idx = None
    for r_idx in range(header_idx + 1, len(grid)):
        row = grid[r_idx]
        if row and row[0].lower().strip() == "total":
            total_row_idx = r_idx
            break
            
    if total_row_idx is None:
        # Fall back to the last row
        total_row_idx = len(grid) - 1
        
    header_row = grid[header_idx]
    total_row = grid[total_row_idx]
    
    res = {}
    gross_vals = []
    disc_vals = []
    taxable_vals = []
    tax_vals = []
    grand_total_vals = []
    
    for c_idx, cell in enumerate(header_row):
        if c_idx >= len(total_row):
            continue
        c = cell.lower().strip()
        val = try_parse_float(total_row[c_idx])
        if val is None:
            continue
            
        if "gros" in c or "gross" in c:
            gross_vals.append(val)
        elif "sch amt" in c or "oth disc" in c or is_discount_label(c):
            disc_vals.append(val)
        elif "trashle" in c or "taxable" in c:
            taxable_vals.append(val)
        elif "the amt" in c or "tax amt" in c or "total tax" in c:
            tax_vals.append(val)
        elif "net payable" in c:
            grand_total_vals.insert(0, val) # net payable has priority over net amt
        elif "net amt" in c or "net amount" in c:
            grand_total_vals.append(val)
            
    if gross_vals:
        res["subtotal"] = gross_vals[0]
    if disc_vals:
        res["discount"] = sum(disc_vals)
    if taxable_vals:
        res["taxable_amount"] = taxable_vals[0]
    if tax_vals:
        res["total_tax"] = tax_vals[0]
    if grand_total_vals:
        res["grand_total"] = grand_total_vals[0]
        
    return res

def extract_field_value(fields: dict, keys: List[str]) -> Any:
    """
    Retrieves a field value from Azure document field definitions.
    Supports dictionary values with standard serialization keys (camelCase/snake_case)
    as well as object attributes.
    """
    for key in keys:
        field = fields.get(key)
        if not field:
            continue
        if isinstance(field, dict):
            for value_key in ["value", "valueString", "value_string", "valueDate", "value_date", "valueFloat", "value_float", "valueNumber", "value_number", "content"]:
                if value_key in field and field[value_key] is not None:
                    return field[value_key]
        else:
            for attr in ["value", "content"]:
                if hasattr(field, attr):
                    val = getattr(field, attr)
                    if val is not None:
                        return val
    return None

def build_grid(table: dict) -> List[List[str]]:
    """Converts sparse Azure table cells into a dense 2D string grid."""
    row_count = table.get("rowCount")
    col_count = table.get("columnCount")
    cells = table.get("cells", [])
    
    if not row_count or not col_count:
        if cells:
            row_count = max(cell.get("rowIndex", 0) for cell in cells) + 1
            col_count = max(cell.get("columnIndex", 0) for cell in cells) + 1
        else:
            return []
            
    grid = [["" for _ in range(col_count)] for _ in range(row_count)]
    for cell in cells:
        r = cell.get("rowIndex", 0)
        c = cell.get("columnIndex", 0)
        content = cell.get("content", "")
        if 0 <= r < row_count and 0 <= c < col_count:
            grid[r][c] = _strip_selection_marks(content)

    return grid

# Azure annotates detected checkbox/tick marks inline as ":selected:" or
# ":unselected:". Handwritten tick marks are common in the Qty column of
# Indian pharma invoices, so these annotations end up glued to real values
# ("1\n:selected:") and break plain numeric parsing. They are never part of
# the printed value, so they are stripped as the grid is built.
_SELECTION_MARK_RE = re.compile(r":(?:un)?selected:", re.IGNORECASE)

def _strip_selection_marks(content: str) -> str:
    if not content or ":" not in content:
        return content
    cleaned = _SELECTION_MARK_RE.sub(" ", content)
    # Collapse the blank lines/space the removal leaves behind, while keeping
    # real newlines that separate genuinely different values.
    lines = [ln.strip() for ln in cleaned.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)

def is_footer_row(row: List[str]) -> bool:
    """Determines if a table row contains subtotal or grand total terms."""
    footer_keywords = ["sub total", "subtotal", "grand total", "net amount", "net payable", "payable amount", "total amt", "total payable", "net amt", "bill amount", "cr/dr note", "roundoff", "round off"]
    for cell in row:
        cell_lower = cell.lower().strip()
        if any(fw in cell_lower for fw in footer_keywords):
            return True
    return False

_CONTINUATION_IDENTITY_FIELDS = ("product", "serial", "amount", "taxable_amount", "gross_amount")

def _is_continuation_fragment(row_data: Dict[str, str]) -> bool:
    """Whether a row is the tail of the item above rather than an item itself.

    Long values (batch, expiry, HSN) sometimes wrap onto a second physical
    row, most often on a continuation page whose header block crowds the
    table. Such a fragment carries none of the fields that identify an item -
    no product, no serial number, no money - but does carry something.
    """
    if any((row_data.get(f) or "").strip() for f in _CONTINUATION_IDENTITY_FIELDS):
        return False
    return any(str(v).strip() for v in row_data.values())


def _absorb_continuation(target: CanonicalLineItem, fragment: CanonicalLineItem) -> None:
    """Fills the target item's empty fields from a continuation fragment.
    Existing values always win - a fragment only supplies what wrapped."""
    for field in ("batch", "expiry", "hsn", "pack"):
        if getattr(target, field, None) in (None, "") and getattr(fragment, field, None):
            setattr(target, field, getattr(fragment, field))


# Header words that only mean something relative to the column beside them.
# "Value" under an SGST heading is a tax amount, not the line's Amount, so
# resolving one in isolation would overwrite the real Amount column.
_CONTEXT_DEPENDENT_HEADERS = {"value", "total", "amt", "amount"}


def _contextual_amount_concept(header_row: List[str], c_idx: int) -> Optional[str]:
    """Resolves a bare 'Value'-style header from its left-hand neighbour,
    mirroring how normalize_header_row treats a standalone 'Value' cell."""
    if c_idx <= 0:
        return None
    previous = re.sub(r'\s+', ' ', header_row[c_idx - 1].lower())
    if "sgst" in previous:
        return "sgst_amount"
    if "cgst" in previous:
        return "cgst_amount"
    if "igst" in previous:
        return "igst_amount"
    return None


def _resolve_header_line(line: str, header_row: List[str], c_idx: int) -> Optional[str]:
    """Maps one line of a multi-line header cell to a column concept.

    Context-dependent words are only accepted when the neighbouring column
    disambiguates them; otherwise the line is skipped rather than guessed.
    """
    concept = normalize_header(line)
    if not concept:
        return None
    if re.sub(r'\s+', ' ', line.lower().strip()) in _CONTEXT_DEPENDENT_HEADERS:
        return _contextual_amount_concept(header_row, c_idx)
    return concept


def _row_has_item_content(row: List[str], ignore_col: int) -> bool:
    """Whether a grid row carries real line-item content, ignoring one column.

    Used to identify the true item rows when re-aligning a vertically offset
    column: that column's own values must not be what makes a row look real,
    otherwise the phantom rows it creates would be counted as items.
    """
    for c_idx, val in enumerate(row):
        if c_idx == ignore_col:
            continue
        if val and val.strip():
            return True
    return False


def _realign_offset_column(
    grid: List[List[str]], hdr_idx: int, c_idx: int
) -> Optional[Dict[int, str]]:
    """Maps a vertically offset column's values back onto the correct rows.

    A fixed one-row shift is not enough: because the offset column's values
    fall between the other columns' rows, Azure inserts extra grid rows that
    hold nothing but one of these values. Those phantom rows swallow a value
    and push every later one out of step again.

    Instead the column's values are read in order and zipped onto the rows
    that actually carry line-item content. Returns None when the two counts
    disagree, in which case the column is left unmapped - a wrong batch
    number is far worse than a missing one, since it is what a recall is
    traced by.
    """
    values: List[str] = []
    for r in range(hdr_idx + 1, len(grid)):
        if c_idx < len(grid[r]):
            val = grid[r][c_idx].strip()
            if val:
                values.append(val)

    # The first value is the header label that slipped into the data rows.
    if values and normalize_header(values[0]):
        values = values[1:]

    item_rows = [
        r for r in range(hdr_idx + 1, len(grid))
        if _row_has_item_content(grid[r], c_idx) and not is_footer_row(grid[r])
    ]

    if len(values) != len(item_rows):
        return None
    return dict(zip(item_rows, values))


def _map_row_to_data(
    row: List[str],
    col_names: List[Optional[str]],
    row_index: Optional[int] = None,
    realigned_columns: Optional[Dict[int, Dict[int, str]]] = None,
) -> Dict[str, str]:
    """Maps a raw grid row's cell values onto canonical column names.

    realigned_columns supplies replacement values for columns printed lower
    than their neighbours (see _realign_offset_column). A row absent from a
    realigned column's mapping is a phantom created by that offset and gets
    no value for it.
    """
    row_data: Dict[str, str] = {}
    for c_idx, val in enumerate(row):
        if c_idx < len(col_names):
            col_name = col_names[c_idx]
            if col_name:
                if realigned_columns and c_idx in realigned_columns:
                    val = realigned_columns[c_idx].get(row_index, "") if row_index is not None else ""
                # Store cell value (use first non-empty value if duplicate column mappings exist)
                if col_name not in row_data or not row_data[col_name]:
                    row_data[col_name] = val
    return row_data

def _build_line_item(
    row_data: Dict[str, Any],
    tbl_idx: int,
    tables: List[dict],
    page_w: float,
    page_h: float,
    r_indices: List[int],
) -> Optional[CanonicalLineItem]:
    """Builds a CanonicalLineItem from an already-assembled row_data dict, or
    returns None if the row carries no real line-item content. r_indices are
    the raw grid row(s) this logical item's cells came from (more than one
    for stacked/multi-physical-row items), used to compute the on-image
    bounding box."""
    product_val = (row_data.get("product") or "").strip()
    batch_val = (row_data.get("batch") or "").strip()
    amount_val = (row_data.get("amount") or "").strip()
    taxable_amount_val = (row_data.get("taxable_amount") or "").strip()

    if not (product_val or batch_val or amount_val or taxable_amount_val):
        return None

    # Quantity extraction prioritizes Total 0y, then t'es, then standard qty column
    qty_total = row_data.get("quantity_total")
    qty_tes = row_data.get("quantity_tes")
    qty_pcs = row_data.get("quantity_pcs")
    qty_raw = row_data.get("quantity")
    serial_raw = row_data.get("serial")

    # Determine if free quantity column has value in row_data
    has_free_in_row = "free_quantity" in row_data and row_data["free_quantity"] is not None and str(row_data["free_quantity"]).strip() != ""

    quantity = None
    free_quantity = None
    split_qty = None
    for qty_candidate in [qty_pcs, qty_raw, qty_total, qty_tes]:
        split_qty = parse_split_quantity(qty_candidate)
        if split_qty:
            break

    if split_qty:
        quantity = split_qty["quantity"]
        free_quantity = split_qty["free_quantity"]
    else:
        if has_free_in_row:
            # Prioritize standard billed/pcs qty column over combined/total qty column
            if qty_pcs is not None and qty_pcs.strip():
                quantity = extract_corrected_qty(qty_pcs, serial_raw)
            elif qty_raw is not None and qty_raw.strip():
                quantity = extract_corrected_qty(qty_raw, serial_raw)
            elif qty_total is not None and qty_total.strip():
                quantity = extract_corrected_qty(qty_total, serial_raw)
        else:
            # Standard prioritization
            if qty_total is not None and qty_total.strip():
                quantity = extract_corrected_qty(qty_total, serial_raw)
            elif qty_tes is not None and qty_tes.strip():
                quantity = extract_corrected_qty(qty_tes, serial_raw)
            elif qty_pcs is not None and qty_pcs.strip():
                quantity = extract_corrected_qty(qty_pcs, serial_raw)
            else:
                quantity = extract_corrected_qty(qty_raw, serial_raw)

        # extract_corrected_qty returns the raw text when nothing in it parsed
        # as a number (e.g. a tick mark OCR'd as "v1"). Recover the quantity
        # from that rather than storing unusable text.
        if quantity is not None and not isinstance(quantity, (int, float)):
            quantity = salvage_tick_marked_qty(quantity)

        # A purchase invoice never bills a negative quantity. A leading minus
        # here is the handwritten tick mark OCR'd as a sign, so take the
        # magnitude rather than storing a negative stock movement.
        if isinstance(quantity, (int, float)) and quantity < 0:
            quantity = abs(quantity)

        free_quantity = parse_decimal_safe(row_data.get("free_quantity"))

    # Discount extraction adds SCH Amt and Dise Amt if both are present
    sch_val = try_parse_float(row_data.get("sch_amt"))
    dise_val = try_parse_float(row_data.get("dise_amt"))
    discount_val = None
    if sch_val is not None and dise_val is not None:
        discount_val = sch_val + dise_val
    elif sch_val is not None:
        discount_val = sch_val
    elif dise_val is not None:
        discount_val = dise_val
    else:
        discount_val = parse_decimal_safe(row_data.get("discount"))

    # GST percent
    gst_percent_raw = row_data.get("gst_percent")
    gst_percent = try_parse_float(gst_percent_raw)
    if gst_percent is None:
        gst_percent = extract_gst_percent(
            row_data.get("sgst_percent"),
            row_data.get("cgst_percent"),
            row_data.get("igst_percent")
        )

    # Amount fallback chain: net amt (amount) -> taxable_amount -> gross_amount.
    # Some invoices have no dedicated "Amount" column at all and instead
    # print only "Gross Amt" (Rate x Qty) per line, with tax handled only at
    # the invoice footer - that figure is this line's amount just as much as
    # a column literally named "Amount" would be.
    amount_raw = row_data.get("amount")
    if amount_raw is None or not str(amount_raw).strip():
        amount_raw = row_data.get("taxable_amount")
    if amount_raw is None or not str(amount_raw).strip():
        amount_raw = row_data.get("gross_amount")
    amount = parse_decimal_safe(amount_raw)

    # Clean up product name: drop a lone leading serial-number line (Azure
    # sometimes merges the "#" and item-name columns into one cell on
    # stacked-header invoices) and collapse remaining newlines to spaces.
    product_name = None
    if product_val:
        name_lines = [ln.strip() for ln in product_val.split("\n") if ln.strip()]
        if len(name_lines) > 1 and re.fullmatch(r'\d+\.?', name_lines[0]):
            name_lines = name_lines[1:]
        product_name = " ".join(name_lines).strip() or None

    # HSN is a single code; if the cell also picked up a trailing UOM/qty
    # fragment on its own line (same merged-cell artifact), keep the first line.
    hsn_val = row_data.get("hsn")
    if hsn_val:
        hsn_val = hsn_val.split("\n")[0].strip() or None

    # Calculate bounding box for the row(s) from raw table cells
    row_bbox = None
    if tbl_idx < len(tables):
        t_obj = tables[tbl_idx]
        t_cells = t_obj.get("cells", []) if isinstance(t_obj, dict) else getattr(t_obj, "cells", [])
        xs, ys = [], []
        r_idx_set = set(r_indices)
        for cell in t_cells:
            c_row = cell.get("rowIndex") if isinstance(cell, dict) else getattr(cell, "rowIndex", -1)
            if c_row in r_idx_set:
                regions = cell.get("boundingRegions", []) if isinstance(cell, dict) else getattr(cell, "boundingRegions", [])
                for reg in regions:
                    poly = reg.get("polygon", []) if isinstance(reg, dict) else getattr(reg, "polygon", [])
                    if len(poly) >= 8:
                        xs.extend(poly[0::2])
                        ys.extend(poly[1::2])
        if xs and ys:
            min_x, max_x = min(xs) / page_w, max(xs) / page_w
            min_y, max_y = min(ys) / page_h, max(ys) / page_h
            row_bbox = [round(min_x, 4), round(min_y, 4), round(max_x, 4), round(max_y, 4)]

    return CanonicalLineItem(
        name=product_name,
        pack=row_data.get("pack") if row_data.get("pack") else None,
        batch=batch_val if batch_val else None,
        expiry=clean_expiry_string(row_data.get("expiry")),
        hsn=hsn_val,
        quantity=quantity,
        free_quantity=free_quantity,
        mrp=parse_decimal_safe(row_data.get("mrp")),
        rate=parse_decimal_safe(row_data.get("rate")),
        discount=discount_val,
        discount_percent=try_parse_float(row_data.get("discount_percent")),
        gst_percent=gst_percent,
        amount=amount,
        confidence=None,
        bounding_box=row_bbox
    )

def normalize_azure_invoice(raw_result: dict) -> CanonicalInvoice:
    """
    Normalizes a raw Azure Document Intelligence analysis response into CanonicalInvoice format.
    Uses the table extraction grid to retrieve pharmaceutical line items instead of standard fields.
    """
    warnings = []
    tables = raw_result.get("tables", [])
    documents = raw_result.get("documents", [])
    pages = raw_result.get("pages", [])
    page_w = 1.0
    page_h = 1.0
    if pages:
        p_obj = pages[0]
        page_w = float(p_obj.get("width", 1.0) if isinstance(p_obj, dict) else getattr(p_obj, "width", 1.0)) or 1.0
        page_h = float(p_obj.get("height", 1.0) if isinstance(p_obj, dict) else getattr(p_obj, "height", 1.0)) or 1.0

    # Page rotation angle from Azure's pages array (degrees, counter-clockwise
    # from horizontal). Needed up front because it corrects the row-ordering
    # sort key below - cell polygons stay in the raw, unrotated image frame,
    # so on a sideways photo (angle near +/-90) "top-to-bottom in the printed
    # table" is "left-to-right in raw pixel space", not "small y".
    page_angle = None
    if pages:
        raw_angle = pages[0].get("angle") if isinstance(pages[0], dict) else getattr(pages[0], "angle", None)
        if raw_angle is not None:
            try:
                page_angle = float(raw_angle)
            except (ValueError, TypeError):
                pass
    page_angle_rad = math.radians(page_angle) if page_angle is not None else 0.0
    
    # 1. Parse all tables into grids
    grids = [build_grid(table) for table in tables]
    
    # 2. Select item tables (supports multi-page / multi-table split invoices)
    item_table_candidates = []
    detection_target_headers = {
        "product", "batch", "expiry", "hsn", "mrp", "rate", "amount", 
        "quantity_total", "quantity_tes", "quantity_pcs", "quantity",
        "taxable_amount", "gross_amount"
    }
    
    all_scored_tables = []
    for table_idx, grid in enumerate(grids):
        best_row_idx = None
        best_score = -1
        best_headers = []
        for row_idx, row in enumerate(grid[:3]):
            headers = normalize_header_row(row)
            score = sum(1 for norm in headers if norm in detection_target_headers)
            if score > best_score:
                best_score = score
                best_row_idx = row_idx
                best_headers = headers
                
        if best_score >= 2 and best_row_idx is not None:
            all_scored_tables.append((table_idx, best_row_idx, best_score, best_headers))
            
    if all_scored_tables:
        all_scored_tables.sort(key=lambda x: x[2], reverse=True)
        primary_idx, primary_row, primary_score, primary_headers = all_scored_tables[0]
        primary_set = set(h for h in primary_headers if h)
        item_table_candidates.append((primary_idx, primary_row, primary_score))
        
        for (tbl_idx, r_idx, score, headers) in all_scored_tables[1:]:
            col_set = set(h for h in headers if h)
            overlap = len(col_set & primary_set)
            if score >= 2 and overlap >= 2 and abs(len(headers) - len(primary_headers)) <= 2:
                item_table_candidates.append((tbl_idx, r_idx, score))
            
    selected_item_table_indices = [c[0] for c in item_table_candidates]
    selected_item_table_idx = selected_item_table_indices[0] if selected_item_table_indices else None
    
    if not item_table_candidates:
        warnings.append("No valid line item table found based on column headers classification.")
        
    # 3. Select the footer table
    selected_footer_table_idx = None
    max_footer_score = -1
    is_footer_horizontal = False
    horizontal_footer_data = None
    
    for table_idx, grid in enumerate(grids):
        # We don't want the same table to be both item and footer unless no other tables exist
        if table_idx in selected_item_table_indices and len(grids) > len(selected_item_table_indices):
            continue
            
        # Try parsing as horizontal summary table first (like CM Associates TABLE 2)
        h_data = parse_horizontal_summary_table(grid)
        if h_data:
            selected_footer_table_idx = table_idx
            is_footer_horizontal = True
            horizontal_footer_data = h_data
            break
            
        score = score_footer_table(grid)
        if score > max_footer_score:
            max_footer_score = score
            selected_footer_table_idx = table_idx
            is_footer_horizontal = False
            
    if selected_footer_table_idx is None:
        warnings.append("No separate footer table identified.")
        
    # 4. Extract footer data
    footer_data = {}
    if selected_footer_table_idx is not None:
        if is_footer_horizontal and horizontal_footer_data:
            footer_data = horizontal_footer_data
        else:
            footer_grid = grids[selected_footer_table_idx]
            for row in footer_grid:
                # Label and value are typically in columns 0/1, but some
                # invoices leave a blank leading column, shifting the real
                # pair rightward - scan for the first two non-empty cells
                # instead of assuming a fixed position.
                lbl_raw, val_str = _footer_label_and_value(row)
                if not lbl_raw:
                    continue
                lbl = lbl_raw.lower().strip()
                val = try_parse_float(val_str) if val_str else None
                if any(k in lbl for k in _SUBTOTAL_LABELS):
                    footer_data["subtotal"] = val
                elif is_discount_label(lbl):
                    footer_data["discount"] = val
                elif "sgst" in lbl:
                    footer_data["sgst"] = val
                elif "cgst" in lbl:
                    footer_data["cgst"] = val
                elif "igst" in lbl:
                    footer_data["igst"] = val
                elif any(x in lbl for x in _GRAND_TOTAL_LABELS):
                    footer_data["grand_total"] = val
                elif "round" in lbl:
                    footer_data["roundoff"] = val

    # 5. Extract document header fields
    doc = documents[0] if documents else {}
    fields = doc.get("fields", {})
    
    invoice_number = extract_field_value(fields, ["InvoiceId", "InvoiceNumber"])
    invoice_date = extract_field_value(fields, ["InvoiceDate"])
    seller_name = extract_field_value(fields, ["VendorName"])
    buyer_name = extract_field_value(fields, ["CustomerName"])
    
    # Extended metadata fields: GST, address, phone, drug license
    seller_gstin = extract_field_value(fields, ["VendorTaxId", "VendorGSTIN"])
    buyer_gstin = extract_field_value(fields, ["CustomerTaxId", "CustomerGSTIN"])
    seller_address = extract_field_value(fields, ["VendorAddress"])
    buyer_address = extract_field_value(fields, ["CustomerAddress"])
    seller_phone = extract_field_value(fields, ["VendorPhone", "VendorTelephone"])
    drug_license = extract_field_value(fields, ["DrugLicenseNumber", "DrugLicense", "DLNumber"])
    
    # Stringify address objects (Azure may return structured dicts with city/state/etc.)
    if isinstance(seller_address, dict):
        parts = [seller_address.get(k, "") for k in ["streetAddress", "city", "state", "postalCode"] if seller_address.get(k)]
        seller_address = ", ".join(parts) if parts else str(seller_address)
    if isinstance(buyer_address, dict):
        parts = [buyer_address.get(k, "") for k in ["streetAddress", "city", "state", "postalCode"] if buyer_address.get(k)]
        buyer_address = ", ".join(parts) if parts else str(buyer_address)
    
    # Regex fallback against document content if standard Azure fields missed metadata
    raw_content = raw_result.get("content", "")
    if raw_content:
        import re
        if not seller_phone:
            phone_match = re.search(r'(?:PHONE|Phone|Ph\.?|Mob\.?|Mobile|Contact)[\s\:\.\-]*([0-9\-\,\ ]{8,})', raw_content, re.IGNORECASE)
            if phone_match:
                seller_phone = phone_match.group(1).split('\n')[0].strip()
        if not drug_license:
            dl_match = re.search(r'(?:Licence\s*No\.?|D\.?L\.?\s*No\.?|20B|21B)[\s\:\.\-]*([0-9A-Z\-\,\/ ]+)', raw_content, re.IGNORECASE)
            if dl_match:
                drug_license = dl_match.group(1).split('\n')[0].strip()
        if not seller_gstin or not buyer_gstin:
            gstin_matches = re.findall(r'\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})\b', raw_content)
            if gstin_matches:
                if not seller_gstin and len(gstin_matches) > 0:
                    seller_gstin = gstin_matches[0]
                if not buyer_gstin and len(gstin_matches) > 1:
                    buyer_gstin = gstin_matches[1]
        if not buyer_address and buyer_name:
            lines = [l.strip() for l in raw_content.split('\n') if l.strip()]
            for idx, l in enumerate(lines):
                if buyer_name.lower() in l.lower() and idx + 1 < len(lines):
                    addr_lines = lines[idx+1:min(idx+4, len(lines))]
                    clean_addr = [al for al in addr_lines if not any(kw in al.lower() for kw in ['gstin', 'licence', 'phone', 'ack no', 'date', 'invoice'])]
                    if clean_addr:
                        buyer_address = ", ".join(clean_addr)
                    break
    
    doc_subtotal = try_parse_float(extract_field_value(fields, ["SubTotal", "TaxableAmount", "TotalTaxableValue", "AmountBeforeTax", "NetTaxable", "GrossTotal"]))
    doc_grand_total = try_parse_float(extract_field_value(fields, ["InvoiceTotal"]))
    # AmountDue is Azure's own "what's actually owed" field, which (unlike
    # InvoiceTotal) usually already has roundoff folded in - preferred over
    # InvoiceTotal as a grand_total fallback for that reason.
    doc_amount_due = try_parse_float(extract_field_value(fields, ["AmountDue"]))
    doc_tax = try_parse_float(extract_field_value(fields, ["TotalTax", "Tax"]))
    doc_total_discount = try_parse_float(extract_field_value(fields, ["TotalDiscount"]))

    # Extracted CGST / SGST individual amount values from item table total row (e.g. Table 3 row 7)
    item_table_cgst = None
    item_table_sgst = None
    # Sum of each line item's own Tot.Tax / Disc.Amt columns (when the
    # invoice prints them directly, e.g. ERP-generated GST invoices) - a
    # last-resort fallback below when nothing else gives us a total tax or
    # discount figure. Preferring the invoice's own printed totals over
    # re-deriving tax from per-item rate/GST% math, since the invoice has
    # already done that arithmetic for us.
    sum_line_tax = 0.0
    has_line_tax = False
    sum_line_discount = 0.0
    has_line_discount = False
    # Sum of each line item's own GrossAmt column (Rate x Qty, before that
    # line's own discount/tax are applied) - used as the subtotal fallback
    # below. Line-item "amount" is whatever the invoice itself calls
    # "Amount", which on some formats (e.g. this one) is already tax- and
    # discount-inclusive; summing that as "subtotal" would double-count tax
    # against the subtotal-discount+tax=grand_total formula. GrossAmt is the
    # true pre-tax, pre-discount figure when the invoice provides it.
    sum_line_gross = 0.0
    has_line_gross = False
    
    # 6. Parse line items from all selected item tables (multi-page/multi-table support)
    line_items = []
    for (tbl_idx, hdr_idx, _) in item_table_candidates:
        item_grid = grids[tbl_idx]
        header_row = item_grid[hdr_idx]
        table_items = []

        col_names = normalize_header_row(header_row)

        # Detect "stacked" item tables: a header cell containing multiple text
        # lines that each name a different column (e.g. "Item Name" on one
        # line, "HSN" on another within the same cell). This shows up on
        # ERP-generated GST invoices (Marg/Busy/Tally-style) that print a
        # CGST/SGST breakout line under each item, so each logical line item
        # spans two physical table rows instead of one.
        #
        # normalize_header_row already resolved the whole multi-line cell
        # where that's a genuine single concept wrapped across lines (e.g.
        # "OTT\n%" -> gst_percent, "Grass\nAmt" -> gross_amount) - those
        # columns are left exactly as-is. Only a cell whose whole text
        # *didn't* resolve to anything is treated as a stack of two concepts,
        # and only when its first line alone names one: e.g. "Item Name\n#\n
        # HSN\n| Qty in SUOM" doesn't match as a whole, but "Item Name" alone
        # maps to product, so a later line naming a different concept ("HSN")
        # becomes this column's secondary meaning. This never fires for an
        # ordinary single-line header (nothing to fall back to), so standard
        # invoices take an unchanged path.
        secondary_col_names: List[Optional[str]] = [None] * len(header_row)
        for c_idx, cell in enumerate(header_row):
            lines = [ln for ln in cell.split("\n") if ln.strip()]
            if len(lines) < 2:
                continue
            primary_concept = col_names[c_idx] if c_idx < len(col_names) else None
            primary_line_idx = 0
            if primary_concept is None:
                # The real label is not always the first line. On a
                # continuation page Azure folds the invoice's own header block
                # into the table header, producing cells like "(NIL)\nM.R.P"
                # or "L.R.\nBatch" where line 0 is stray text. Scanning every
                # line for the first that names a column recovers those,
                # instead of dropping MRP/Rate/HSN for the whole page.
                for line_idx, line in enumerate(lines):
                    concept = _resolve_header_line(line, header_row, c_idx)
                    if concept:
                        primary_concept = concept
                        primary_line_idx = line_idx
                        col_names[c_idx] = concept
                        break
            if primary_concept is None:
                continue
            for line in lines[primary_line_idx + 1:]:
                concept = normalize_header(line)
                if concept and concept != primary_concept:
                    secondary_col_names[c_idx] = concept
                    break
        is_stacked_header = any(c is not None for c in secondary_col_names)

        # Detect a column printed slightly lower than its neighbours.
        #
        # Azure assigns each cell to a row by vertical position. When one
        # column's text sits about half a row below the rest - which happens
        # on invoices where the Batch column is typeset lower - that column's
        # header lands in the FIRST DATA ROW and every value lands one row
        # below its true row. The symptom is a whole column of empty values
        # plus a trailing phantom row carrying the last item's value.
        #
        # The evidence is unambiguous: a header label (e.g. "Batch") sitting
        # in a data row, above a column the header row left blank. Nothing
        # else produces that, so the column is re-aligned by reading it one
        # row down. A correctly-typeset table never triggers this.
        # realigned_columns[col_index][grid_row] -> value for that row
        realigned_columns: Dict[int, Dict[int, str]] = {}
        if hdr_idx + 1 < len(item_grid):
            first_data_row = item_grid[hdr_idx + 1]
            for c_idx in range(len(col_names)):
                if col_names[c_idx] is not None:
                    continue
                if c_idx >= len(first_data_row) or header_row[c_idx].strip():
                    continue
                concept = normalize_header(first_data_row[c_idx])
                # Only re-align onto a concept this table doesn't already have,
                # so a stray word in a data cell can't hijack a mapped column.
                if not concept or concept in col_names:
                    continue

                mapping = _realign_offset_column(item_grid, hdr_idx, c_idx)
                if mapping is None:
                    warnings.append(
                        f"Column '{concept}' appears to be printed below its header row, but "
                        f"its values could not be matched to the line items, so it was skipped."
                    )
                    continue

                col_names[c_idx] = concept
                realigned_columns[c_idx] = mapping
                warnings.append(
                    f"Column '{concept}' was printed below its header row and has been "
                    f"re-aligned to the line items."
                )

        pending_row_data: Optional[Dict[str, Any]] = None
        pending_r_indices: List[int] = []

        def flush_pending():
            nonlocal pending_row_data, pending_r_indices, sum_line_tax, has_line_tax, sum_line_discount, has_line_discount, sum_line_gross, has_line_gross
            if pending_row_data is not None:
                pending_item = _build_line_item(pending_row_data, tbl_idx, tables, page_w, page_h, pending_r_indices)
                if pending_item is not None:
                    table_items.append(pending_item)
                    tax_val = try_parse_float(pending_row_data.get("line_tax_amount"))
                    if tax_val is not None:
                        sum_line_tax += tax_val
                        has_line_tax = True
                    if pending_item.discount is not None:
                        sum_line_discount += pending_item.discount
                        has_line_discount = True
                    gross_val = try_parse_float(pending_row_data.get("gross_amount"))
                    if gross_val is not None:
                        sum_line_gross += gross_val
                        has_line_gross = True
            pending_row_data = None
            pending_r_indices = []

        for r_idx in range(hdr_idx + 1, len(item_grid)):
            row = item_grid[r_idx]

            # Check if this row is the Total row of the item table
            is_item_total_row = (row and row[0].lower().strip() == "total") or (len(row) > 2 and row[2].lower().strip() == "total")

            # Skip rows containing footer content unless it is the total row we want to inspect for taxes
            if is_footer_row(row) and not is_item_total_row:
                continue

            row_data = _map_row_to_data(row, col_names, r_idx, realigned_columns)
            product_val = (row_data.get("product") or "").strip()

            # If it is the total row, extract CGST and SGST amount values and skip item conversion
            if is_item_total_row or product_val.lower() == "total":
                if is_stacked_header:
                    flush_pending()
                for c_idx, val in enumerate(row):
                    if c_idx < len(col_names):
                        col_name = col_names[c_idx]
                        if col_name == "cgst_amount":
                            item_table_cgst = try_parse_float(val)
                        elif col_name == "sgst_amount":
                            item_table_sgst = try_parse_float(val)
                continue

            if not is_stacked_header:
                item = _build_line_item(row_data, tbl_idx, tables, page_w, page_h, [r_idx])
                if item is not None:
                    # A row with no product, serial or money is the wrapped
                    # tail of the item above, not a new item of its own.
                    if table_items and _is_continuation_fragment(row_data):
                        _absorb_continuation(table_items[-1], item)
                        continue
                    table_items.append(item)
                    tax_val = try_parse_float(row_data.get("line_tax_amount"))
                    if tax_val is not None:
                        sum_line_tax += tax_val
                        has_line_tax = True
                    if item.discount is not None:
                        sum_line_discount += item.discount
                        has_line_discount = True
                    gross_val = try_parse_float(row_data.get("gross_amount"))
                    if gross_val is not None:
                        sum_line_gross += gross_val
                        has_line_gross = True
                continue

            # Stacked-header path: a row carrying its own Amount (or Taxable
            # Amount) starts a new logical item; otherwise it's the secondary
            # physical row (HSN/CGST/SGST breakout) belonging to the item
            # just above it, so merge it in using the header's second line
            # of meaning per column instead of starting a new item. Amount is
            # the discriminator, not product name: on a stacked table the
            # "product" column's *primary* concept typically also covers the
            # continuation row's own first cell (e.g. col0 is "product" on
            # top, "hsn" underneath, but both physically live in column 0),
            # so product_val is non-empty on both rows and can't tell them
            # apart - the item's total Amount only ever appears once, on the
            # row that actually starts the item.
            looks_like_new_item = bool((row_data.get("amount") or "").strip()) or bool((row_data.get("taxable_amount") or "").strip())
            if looks_like_new_item:
                flush_pending()
                pending_row_data = row_data
                pending_r_indices = [r_idx]
            else:
                if pending_row_data is None:
                    continue
                secondary_data = _map_row_to_data(row, secondary_col_names)
                for key, val in secondary_data.items():
                    if val and not pending_row_data.get(key):
                        pending_row_data[key] = val
                pending_r_indices.append(r_idx)

        flush_pending()

        # Azure occasionally assigns a stray footnote/formula fragment a rowIndex
        # that lands it mid-table; re-sort this table's rows by actual reading
        # position so the review screen matches the printed invoice order. Cell
        # polygons are in the raw, unrotated image frame, so on a rotated photo
        # "top-to-bottom in print" isn't "small y" in that frame - rotate the
        # bbox center by the page angle first to recover true reading order.
        if all(it.bounding_box for it in table_items):
            table_items.sort(key=lambda it: _row_reading_order_key(it.bounding_box, page_angle_rad))
        line_items.extend(table_items)

    # Fallback to Azure prebuilt document Items if custom table parsing returned 0 line items
    if not line_items and fields:
        items_field = fields.get("Items", {})
        items_arr = items_field.get("valueArray", []) if isinstance(items_field, dict) else []
        for it in items_arr:
            val_obj = it.get("valueObject", {}) if isinstance(it, dict) else {}
            if not val_obj:
                continue
            desc_val = extract_field_value(val_obj, ["Description", "ProductCode"])
            if desc_val:
                line_items.append(CanonicalLineItem(
                    name=str(desc_val),
                    batch=extract_field_value(val_obj, ["Batch"]),
                    hsn=extract_field_value(val_obj, ["TaxCode", "HSNCode"]),
                    quantity=try_parse_float(extract_field_value(val_obj, ["Quantity"])),
                    mrp=parse_decimal_safe(extract_field_value(val_obj, ["UnitPrice"])),
                    rate=parse_decimal_safe(extract_field_value(val_obj, ["UnitPrice"])),
                    amount=parse_decimal_safe(extract_field_value(val_obj, ["Amount"])),
                    confidence=None
                ))

    # 7. Merge header fields (footer data takes precedence for totals)
    subtotal = footer_data.get("subtotal") if footer_data.get("subtotal") is not None else doc_subtotal
    discount = footer_data.get("discount")
    cgst = footer_data.get("cgst")
    sgst = footer_data.get("sgst")
    igst = footer_data.get("igst")
    # None (not 0) when the invoice printed no roundoff line at all, so the
    # frontend can tell "no roundoff" apart from "rounds off by exactly 0".
    roundoff = footer_data.get("roundoff")
    # grand_total prefers, in order: the invoice's own printed total/payable
    # label, then Azure's AmountDue field (usually already has roundoff
    # folded in), then Azure's InvoiceTotal (often the pre-roundoff figure).
    if footer_data.get("grand_total") is not None:
        grand_total = footer_data["grand_total"]
    elif doc_amount_due is not None:
        grand_total = doc_amount_due
    else:
        grand_total = doc_grand_total

    # Smart fallback for subtotal if not explicitly extracted by OCR. Prefer
    # the sum of each line's own GrossAmt (Rate x Qty, pre-discount/pre-tax)
    # when the invoice provides it - that's the figure the
    # subtotal-discount+tax=grand_total formula expects. Falling back to
    # summing line_items[].amount is only correct when "amount" itself is
    # pre-tax (true on many pharma invoice formats); on formats where
    # "amount" is the final tax-inclusive line total (this one), summing it
    # would double-count tax against the formula above.
    if subtotal is None:
        if has_line_gross:
            subtotal = round(sum_line_gross, 2)
        else:
            line_amounts = [item.amount for item in line_items if item.amount is not None]
            if line_amounts:
                subtotal = round(sum(line_amounts), 2)
            elif grand_total is not None:
                tax_sum = (cgst or 0.0) + (sgst or 0.0) + (igst or 0.0)
                subtotal = round(grand_total + (discount or 0.0) - tax_sum, 2)

    # Fallback to item table total row tax amounts if summary totals did not provide CGST/SGST explicitly
    if cgst is None and item_table_cgst is not None:
        cgst = item_table_cgst
    if sgst is None and item_table_sgst is not None:
        sgst = item_table_sgst

    # If nothing above gave us a tax total, prefer the invoice's own
    # precomputed totals (Azure's doc-level TotalTax field, or failing that
    # the sum of each line's own Tot.Tax column) over re-deriving it from
    # per-item rate/GST% math. Azure doesn't split these into CGST/SGST, so
    # the combined figure is carried on cgst alone (sgst stays None) -
    # frontend tax totals sum cgst+sgst+igst, so this still surfaces correctly.
    if cgst is None and sgst is None:
        if doc_tax is not None:
            cgst = doc_tax
        elif has_line_tax:
            cgst = round(sum_line_tax, 2)

    # Same precedence for discount: the invoice's own printed discount
    # figure, then the sum of each line's own Disc.Amt column.
    if discount is None:
        if doc_total_discount is not None:
            discount = doc_total_discount
        elif has_line_discount:
            discount = round(sum_line_discount, 2)

    # Discount is stored as the magnitude to deduct, because every consumer
    # subtracts it (subtotal - discount + tax = total). Invoices that print
    # the deduction as "-151.42" would otherwise be added back, turning a
    # discount into a surcharge and failing the review screen's math check.
    if isinstance(discount, (int, float)) and discount < 0:
        discount = abs(discount)


    # 8. Calculate extraction confidence
    item_table_found = (selected_item_table_idx is not None)
    has_line_items = (len(line_items) > 0)
    has_grand_total = (grand_total is not None)
    has_header_totals = (
        invoice_number is not None or 
        invoice_date is not None or 
        seller_name is not None or 
        subtotal is not None or 
        grand_total is not None
    )
    
    if item_table_found and has_line_items and has_grand_total:
        confidence = 0.85
    elif has_header_totals:
        confidence = 0.65
    else:
        confidence = 0.40
        
    # Derive Amount for any line the invoice didn't give us one for, using the
    # formula this invoice's own readable rows demonstrate. Runs after every
    # line item exists so it has the full set to learn from.
    amount_fill = fill_missing_amounts(line_items)

    # 9. Populate metadata
    raw_engine_metadata = {
        "model_id": raw_result.get("modelId"),
        "table_count": len(tables),
        "document_count": len(documents),
        "selected_item_table_index": selected_item_table_idx,
        "selected_footer_table_index": selected_footer_table_idx,
        "item_table_row_count": len(grids[selected_item_table_idx]) if selected_item_table_idx is not None else 0,
        "item_table_column_count": len(grids[selected_item_table_idx][0]) if selected_item_table_idx is not None and len(grids[selected_item_table_idx]) > 0 else 0,
        "warnings": warnings,
        "doc_fields_tax": doc_tax,
        "amount_formula": amount_fill["formula"],
        "estimated_amount_count": amount_fill["filled"],
        "page_angle": page_angle
    }
    
    # Add optional keys if horizontal table parsed them
    if "taxable_amount" in footer_data:
        raw_engine_metadata["taxable_amount"] = footer_data["taxable_amount"]
    if "total_tax" in footer_data:
        raw_engine_metadata["total_tax"] = footer_data["total_tax"]
    if "roundoff" in footer_data:
        raw_engine_metadata["roundoff"] = footer_data["roundoff"]
        
    return CanonicalInvoice(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        seller_name=seller_name,
        buyer_name=buyer_name,
        seller_gstin=str(seller_gstin) if seller_gstin else None,
        buyer_gstin=str(buyer_gstin) if buyer_gstin else None,
        seller_address=str(seller_address) if seller_address else None,
        buyer_address=str(buyer_address) if buyer_address else None,
        seller_phone=str(seller_phone) if seller_phone else None,
        drug_license=str(drug_license) if drug_license else None,
        subtotal=subtotal,
        discount=discount,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        grand_total=grand_total,
        roundoff=roundoff,
        line_items=line_items,
        confidence=confidence,
        extraction_engine="azure_document_intelligence",
        raw_engine_metadata=raw_engine_metadata,
        page_angle=page_angle,
        page_angles=[page_angle if page_angle is not None else 0.0],
    )
