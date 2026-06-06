"""
Wide-Table Evidence Detector for Indian Pharma Invoice Tables.

Evaluates layout evidence to determine whether a table region is a wide
pharma-style table (≥10 columns: product, HSN, pack, company, batch,
qty, free, rate, disc, exp, MRP, GST%, amount, etc.).

All signals are topology-based — no vendor name, invoice number, or
exact expected row text is used.  This module is the gatekeeper:
downstream column-merge gating, header-anchor attachment, and OCR-block
splitting all key off `WideTableEvidence.is_wide`.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.logger import logger
from models.layout_models import OCRBlock, TableRegion, GeometryBox


# ─── Constants ────────────────────────────────────────────────────────

# Generic pharma header tokens — order-independent, case-insensitive.
# Intentionally broad to cover many Indian distributor invoice formats.
_HEADER_LABEL_RE = re.compile(
    r"\b("
    r"PRODUCT|ITEM|DESCRIPTION|PARTICULARS|MEDICINE|DRUG|NAME"
    r"|HSN|SAC"
    r"|BATCH|B\.?\s*NO|LOT"
    r"|QTY|QUANTITY|BILLED"
    r"|FREE|SCHEME|SCH"
    r"|RATE|PTR|PRICE"
    r"|DISC|DISCOUNT|TD|CD"
    r"|EXP|EXPIRY"
    r"|MRP"
    r"|GST|CGST|SGST|IGST|TAX"
    r"|AMOUNT|AMT|VALUE|NET"
    r"|PACK|COMPANY|MFR|MANUFACTURER"
    r"|SR\.?\s*NO|S\.?\s*NO|SHO|SL|NO"
    r")\b",
    re.IGNORECASE,
)

# Patterns for typical pharma item-row field types.
_DECIMAL_RE = re.compile(r"^\s*[\d,]+\.\d{1,2}\s*$")           # 118.00
_DATE_RE = re.compile(r"^\s*\d{1,2}[/-]\d{2,4}\s*$")           # 05/27
_SMALL_INT_RE = re.compile(r"^\s*\d{1,8}\s*$")                 # 5
_BATCH_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{3,18}$")          # BA2341
_HSN_RE = re.compile(r"^\d{6,8}$")                             # 30049099

# Minimum confidence to enter wide-table mode.
# Raised slightly to be more robust, combined with estimated columns filter.
WIDE_TABLE_CONFIDENCE_THRESHOLD = 0.50

# Minimum column count for a legitimate wide pharma table.
WIDE_TABLE_MIN_COLUMNS = 10


@dataclass
class WideTableEvidence:
    """Result of wide-table evidence evaluation."""
    is_wide: bool = False
    confidence: float = 0.0
    estimated_column_count: int = 0
    signals: Dict[str, Any] = field(default_factory=dict)


# ─── Public API ───────────────────────────────────────────────────────

def detect_wide_table(
    ocr_blocks: List[OCRBlock],
    table_regions: List[TableRegion],
) -> WideTableEvidence:
    """
    Evaluate layout evidence for wide-table mode activation.

    Parameters
    ----------
    ocr_blocks : list[OCRBlock]
        All normalised OCR tokens for the document.
    table_regions : list[TableRegion]
        Table regions detected by TSR (heuristic or PPStructure).

    Returns
    -------
    WideTableEvidence
        ``is_wide=True`` when composite confidence ≥ threshold.
    """
    if not ocr_blocks:
        return WideTableEvidence()

    signals: Dict[str, Any] = {}

    # ── Signal 1: Header-row label density ────────────────────────
    header_score, header_label_count = _score_header_labels(ocr_blocks)
    header_expanded_column_count = _expanded_header_column_count(ocr_blocks)
    if header_expanded_column_count >= WIDE_TABLE_MIN_COLUMNS:
        header_label_count = max(header_label_count, header_expanded_column_count)
        header_score = 1.0
    signals["header_label_count"] = header_label_count
    signals["header_expanded_column_count"] = header_expanded_column_count
    signals["header_score"] = round(header_score, 3)

    # ── Signal 2: Vertical whitespace gap count (column separators)
    gap_count = _count_column_gaps(ocr_blocks)
    gap_score = min(1.0, gap_count / 12.0)  # 12 gaps → perfect score
    signals["column_gap_count"] = gap_count
    signals["gap_score"] = round(gap_score, 3)

    # ── Signal 3: Per-row field diversity ─────────────────────────
    diversity_score, avg_fields = _score_row_field_diversity(ocr_blocks)
    signals["avg_field_types_per_row"] = round(avg_fields, 2)
    signals["diversity_score"] = round(diversity_score, 3)

    # ── Signal 4: Median tokens per row ───────────────────────────
    med_tokens = _median_tokens_per_row(ocr_blocks)
    token_score = min(1.0, med_tokens / 12.0)  # 12+ tokens/row → max
    signals["median_tokens_per_row"] = med_tokens
    signals["token_score"] = round(token_score, 3)

    # ── Signal 5: TSR column count (if available) ─────────────────
    tsr_col_count = max((len(tr.columns) for tr in table_regions), default=0)
    tsr_score = min(1.0, tsr_col_count / 12.0)
    signals["tsr_column_count"] = tsr_col_count
    signals["tsr_score"] = round(tsr_score, 3)

    # ── Composite Confidence ──────────────────────────────────────
    # Adjusted weights to prioritize physical layout structure (gap and TSR counts)
    # over raw keyword matches to be more robust to OCR noise/low-confidence headers.
    composite = (
        header_score * 0.20
        + gap_score * 0.25
        + diversity_score * 0.20
        + token_score * 0.10
        + tsr_score * 0.25
    )
    composite = round(max(0.0, min(1.0, composite)), 3)

    strong_pharma_header = (
        header_label_count >= 7
        and diversity_score >= 0.60
        and max(tsr_col_count, header_expanded_column_count) >= 3
    )

    estimated_cols = max(tsr_col_count, gap_count + 1, header_label_count, header_expanded_column_count)
    if strong_pharma_header:
        estimated_cols = max(estimated_cols, WIDE_TABLE_MIN_COLUMNS)

    # A wide table requires both composite confidence >= threshold and at least 8 estimated columns.
    strong_expanded_header = header_expanded_column_count >= WIDE_TABLE_MIN_COLUMNS and composite >= 0.45
    is_wide = (
        ((composite >= WIDE_TABLE_CONFIDENCE_THRESHOLD) and (estimated_cols >= 8))
        or strong_expanded_header
        or (strong_pharma_header and composite >= 0.42)
    )
    signals["strong_pharma_header"] = strong_pharma_header

    evidence = WideTableEvidence(
        is_wide=is_wide,
        confidence=composite,
        estimated_column_count=estimated_cols,
        signals=signals,
    )

    logger.info(
        f"[WIDE TABLE] is_wide={is_wide} | confidence={composite} "
        f"| est_cols={estimated_cols} | signals={signals}"
    )
    return evidence


# ─── Internal signal scorers ──────────────────────────────────────────

def _score_header_labels(blocks: List[OCRBlock]) -> Tuple[float, int]:
    """
    Score header-label evidence by scanning all clustered rows on the page
    for column-label tokens matching pharma header patterns.
    """
    if not blocks:
        return 0.0, 0

    valid = [b for b in blocks if b.normalized_geometry]
    if not valid:
        return 0.0, 0

    # Cluster all blocks into rows dynamically
    rows = _cluster_blocks_into_rows(valid)
    max_label_count = 0
    for r in rows:
        seen_labels = set()
        for b in r:
            text = (b.text or "").strip().upper()
            if len(text) > 30:
                continue
            matches = _HEADER_LABEL_RE.findall(text)
            for m in matches:
                seen_labels.add(m.upper())
        if len(seen_labels) > max_label_count:
            max_label_count = len(seen_labels)

    # 6+ distinct labels in any single row → strong evidence (score 1.0)
    score = min(1.0, max_label_count / 6.0)
    return score, max_label_count


def _expanded_header_column_count(blocks: List[OCRBlock]) -> int:
    """
    Estimate header-derived columns after splitting grouped header clusters.

    This catches wide layouts where OCR/TSR grouped labels into mega-cells like
    ``HSN CODE PACK CMPNY BATCH NO``. It is still generic: it relies only on
    label geometry and known pharma header vocabulary, not vendor identity.
    """
    valid = [b for b in blocks if b.normalized_geometry]
    if not valid:
        return 0

    rows = _cluster_blocks_into_rows(valid)
    if not rows:
        return 0

    xs = [coord for b in valid for coord in (b.normalized_geometry.min_x, b.normalized_geometry.max_x)]
    table_min_x = min(xs) if xs else None
    table_max_x = max(xs) if xs else None

    try:
        from services.layout_pipeline.header_anchor import derive_header_column_bands
    except Exception:
        return 0

    max_count = 0
    for row in rows:
        bands = derive_header_column_bands(row, table_min_x=table_min_x, table_max_x=table_max_x)
        max_count = max(max_count, len(bands))
    return max_count


def _count_column_gaps(blocks: List[OCRBlock]) -> int:
    """
    Count distinct vertical whitespace gaps in the token x-histogram.
    Many gaps imply many columns.
    """
    valid = [b for b in blocks if b.normalized_geometry]
    if not valid:
        return 0

    # Build x-occupancy histogram
    max_x = int(max(b.normalized_geometry.max_x for b in valid)) + 10
    hist = [0] * max_x

    for b in valid:
        g = b.normalized_geometry
        start = max(0, int(g.min_x))
        end = min(max_x, int(g.max_x))
        for x in range(start, end):
            hist[x] += 1

    # Find gaps (runs of zeros ≥ 3px wide)
    gap_count = 0
    in_gap = False
    gap_width = 0
    for val in hist:
        if val == 0:
            gap_width += 1
            if gap_width >= 3 and not in_gap:
                gap_count += 1
                in_gap = True
        else:
            in_gap = False
            gap_width = 0

    return gap_count


def _score_row_field_diversity(blocks: List[OCRBlock]) -> Tuple[float, float]:
    """
    Check how many distinct field types (product-text, batch-like,
    date-like, decimal-amount, integer-qty, HSN-like) each row contains.

    Returns (score_0_to_1, avg_field_types_per_row).
    """
    valid = [b for b in blocks if b.normalized_geometry]
    if not valid:
        return 0.0, 0.0

    # Cluster into rows by y-coordinate
    rows = _cluster_blocks_into_rows(valid)
    if not rows:
        return 0.0, 0.0

    diversities: List[int] = []
    for row_blocks in rows:
        field_types: set = set()
        for b in row_blocks:
            text = (b.text or "").strip()
            # Split by whitespace to check sub-tokens
            tokens = text.split()
            for t in tokens:
                compact = re.sub(r"\s+", "", t.upper())
                if not compact:
                    continue
                if _DECIMAL_RE.match(t):
                    field_types.add("decimal")
                elif _DATE_RE.match(t):
                    field_types.add("date")
                elif _HSN_RE.match(compact):
                    field_types.add("hsn")
                elif _BATCH_RE.match(compact) and re.search(r"[A-Z]", compact) and re.search(r"\d", compact):
                    field_types.add("batch")
                elif _SMALL_INT_RE.match(t):
                    field_types.add("integer")
                elif len(compact) >= 4 and sum(1 for c in compact if c.isalpha()) >= 3:
                    field_types.add("alpha_text")
        diversities.append(len(field_types))

    if not diversities:
        return 0.0, 0.0

    # Only consider rows with at least some content (≥3 blocks)
    content_rows = [d for d, r in zip(diversities, rows) if len(r) >= 3]
    if not content_rows:
        return 0.0, 0.0

    avg = sum(content_rows) / len(content_rows)
    # 4+ field types per row on average → strong evidence
    score = min(1.0, avg / 4.0)
    return score, avg


def _median_tokens_per_row(blocks: List[OCRBlock]) -> int:
    """Compute median token count across clustered rows."""
    valid = [b for b in blocks if b.normalized_geometry]
    if not valid:
        return 0

    rows = _cluster_blocks_into_rows(valid)
    if not rows:
        return 0

    counts = [len(r) for r in rows if len(r) >= 2]
    if not counts:
        return 0

    return int(statistics.median(counts))


def _cluster_blocks_into_rows(blocks: List[OCRBlock]) -> List[List[OCRBlock]]:
    """
    Lightweight row clustering by y-coordinate bucketing.
    Groups blocks whose center_y values are within a tolerance band.
    """
    if not blocks:
        return []

    sorted_blocks = sorted(blocks, key=lambda b: b.normalized_geometry.center_y)

    # Estimate row height from median block height
    heights = [b.normalized_geometry.max_y - b.normalized_geometry.min_y for b in sorted_blocks]
    med_h = statistics.median(heights) if heights else 15.0
    tolerance = max(5.0, med_h * 0.6)

    rows: List[List[OCRBlock]] = []
    current_row: List[OCRBlock] = [sorted_blocks[0]]
    current_y = sorted_blocks[0].normalized_geometry.center_y

    for b in sorted_blocks[1:]:
        by = b.normalized_geometry.center_y
        if abs(by - current_y) <= tolerance:
            current_row.append(b)
        else:
            rows.append(current_row)
            current_row = [b]
            current_y = by

    if current_row:
        rows.append(current_row)

    return rows


# ─── Fused Block Splitter Logic ────────────────────────────────────────

def should_split_block(text: str) -> bool:
    """Assess whether a block contains horizontally fused columns/cells."""
    tokens = text.strip().split()
    if len(tokens) < 2:
        return False

    has_date = False
    has_decimal = False
    has_hsn = False
    has_batch = False
    has_alpha_len3 = False
    has_integer = False

    date_pat = re.compile(r"^\d{2}[/-]\d{2,4}$")
    decimal_pat = re.compile(r"^\d+\.\d{2}$")
    hsn_pat = re.compile(r"^\d{6,8}$")
    # Batch pattern: alphanumeric, starts with letter/digit, contains at least one letter and digit
    batch_pat = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d\-]{4,20}$")

    for t in tokens:
        # Strip trailing/leading punctuation
        t_clean = re.sub(r"^[^\w./-]+|[^\w./-]+$", "", t)
        if date_pat.match(t_clean):
            has_date = True
        elif decimal_pat.match(t_clean):
            has_decimal = True
        elif hsn_pat.match(t_clean):
            has_hsn = True
        elif batch_pat.match(t_clean):
            has_batch = True
        elif t_clean.isdigit():
            has_integer = True
        elif len(t_clean) >= 3 and t_clean.isalpha():
            has_alpha_len3 = True

    # 1. Rate/Expiry or Discount/Rate/Expiry (e.g. "135.16 07/27")
    if has_decimal and has_date:
        return True
    # 2. Product + HSN (e.g. "CNDERO MET 30049099")
    if has_hsn and has_alpha_len3:
        return True
    # 2b. HSN + pack/free quantity (e.g. "30049099 10 S")
    if has_hsn and has_integer:
        return True
    # 3. Product + Batch (e.g. "LUPIN UB02123")
    if has_batch and has_alpha_len3:
        return True
    # 4. Product + Qty + Rate/Amount (e.g. "LUPIN 10 135.16")
    if has_alpha_len3 and has_decimal and has_integer:
        return True

    return False


def split_fused_block(block: OCRBlock) -> List[OCRBlock]:
    """Split a fused block horizontally and interpolate geometry boxes."""
    text = block.text
    if not should_split_block(text):
        return [block]

    geom = block.normalized_geometry
    if not geom:
        return [block]

    orig_geom = block.original_geometry

    # Find character index spans for each whitespace-separated word
    words_info = []
    for match in re.finditer(r"\S+", text):
        words_info.append((match.group(), match.start(), match.end()))

    if len(words_info) <= 1:
        return [block]

    total_chars = len(text)
    split_blocks = []

    for idx, (word, start_idx, end_idx) in enumerate(words_info):
        w_norm_min_x = geom.min_x + (start_idx / total_chars) * (geom.max_x - geom.min_x)
        w_norm_max_x = geom.min_x + (end_idx / total_chars) * (geom.max_x - geom.min_x)

        new_norm_geom = GeometryBox(
            min_x=w_norm_min_x,
            max_x=w_norm_max_x,
            min_y=geom.min_y,
            max_y=geom.max_y,
            center_x=(w_norm_min_x + w_norm_max_x) / 2.0,
            center_y=geom.center_y,
        )

        polygon = [
            (w_norm_min_x, geom.min_y),
            (w_norm_max_x, geom.min_y),
            (w_norm_max_x, geom.max_y),
            (w_norm_min_x, geom.max_y),
        ]

        new_orig_geom = None
        if orig_geom:
            w_orig_min_x = orig_geom.min_x + (start_idx / total_chars) * (orig_geom.max_x - orig_geom.min_x)
            w_orig_max_x = orig_geom.min_x + (end_idx / total_chars) * (orig_geom.max_x - orig_geom.min_x)
            new_orig_geom = GeometryBox(
                min_x=w_orig_min_x,
                max_x=w_orig_max_x,
                min_y=orig_geom.min_y,
                max_y=orig_geom.max_y,
                center_x=(w_orig_min_x + w_orig_max_x) / 2.0,
                center_y=orig_geom.center_y,
            )

        new_block = OCRBlock(
            id=f"{block.id}_split_{idx}" if block.id else f"split_{idx}",
            raw_text=word,
            text=word,
            polygon=polygon,
            original_geometry=new_orig_geom,
            normalized_geometry=new_norm_geom,
            confidence=block.confidence,
        )
        split_blocks.append(new_block)

    return split_blocks


def split_fused_blocks(ocr_blocks: List[OCRBlock]) -> List[OCRBlock]:
    """Helper to process and split a list of OCRBlocks."""
    split_blocks = []
    for b in ocr_blocks:
        split_blocks.extend(split_fused_block(b))
    return split_blocks
