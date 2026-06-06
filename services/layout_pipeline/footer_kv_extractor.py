"""
Footer Key-Value Extractor — Pre-canonicalization footer field extraction.

Runs on OCR blocks **below** the selected item table bounding box to
extract label→value pairs for subtotal, tax, discount, and grand total
fields.  Results feed into `spatial_reconstruction.py` before the
canonical invoice builder is invoked.

All label matching is generic — no vendor names or invoice-specific text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.logger import logger
from models.layout_models import OCRBlock, GeometryBox


# ─── Label patterns ──────────────────────────────────────────────────

_SUBTOTAL_RE = re.compile(
    r"\b(SUB\s*TOTAL|TAXABLE\s*VALUE|GOODS\s*VALUE|GROSS\s*AMOUNT)\b",
    re.IGNORECASE,
)
_DISCOUNT_RE = re.compile(
    r"\b(DISCOUNT|DISC|LESS|TRADE\s*DISC|TD|CD|CASH\s*DISC)\b",
    re.IGNORECASE,
)
_SGST_RE = re.compile(r"\bS\.?\s*G\.?\s*S\.?\s*T\.?\b", re.IGNORECASE)
_CGST_RE = re.compile(r"\bC\.?\s*G\.?\s*S\.?\s*T\.?\b", re.IGNORECASE)
_IGST_RE = re.compile(r"\bI\.?\s*G\.?\s*S\.?\s*T\.?\b", re.IGNORECASE)
_ROUNDOFF_RE = re.compile(r"\b(ROUND\s*OFF|ROUNDOFF|ROUNDING)\b", re.IGNORECASE)
_GRAND_TOTAL_RE = re.compile(
    r"\b(GRAND\s*TOTAL|NET\s*AMT|NET\s*AMOUNT|NET\s*PAYABLE"
    r"|BILL\s*AMOUNT|PAYABLE\s*AMOUNT|TOTAL\s*PAYABLE"
    r"|TOTAL\s*AMT|AMOUNT\s*PAYABLE|INVOICE\s*AMOUNT)\b",
    re.IGNORECASE,
)

# For extracting numeric amounts adjacent to labels.
_AMOUNT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:Rs\.?\s*)?(?:₹\s*)?-?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d{1,2})?(?![A-Za-z0-9])",
    re.IGNORECASE,
)

_LABEL_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("subtotal", _SUBTOTAL_RE),
    ("discount", _DISCOUNT_RE),
    ("sgst", _SGST_RE),
    ("cgst", _CGST_RE),
    ("igst", _IGST_RE),
    ("roundoff", _ROUNDOFF_RE),
    ("grand_total", _GRAND_TOTAL_RE),
]


@dataclass
class FooterField:
    """A single extracted footer key-value pair."""
    label: str
    value: Optional[float] = None
    raw_text: str = ""
    confidence: float = 0.0
    source_block_ids: List[str] = field(default_factory=list)


@dataclass
class FooterExtractionResult:
    """Result of pre-canonicalization footer extraction."""
    fields: List[FooterField] = field(default_factory=list)
    block_count_below_table: int = 0
    line_count: int = 0
    signals: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fields": [
                {
                    "label": f.label,
                    "value": f.value,
                    "raw_text": f.raw_text,
                    "confidence": f.confidence,
                }
                for f in self.fields
            ],
            "block_count_below_table": self.block_count_below_table,
            "line_count": self.line_count,
        }


def extract_footer_kv(
    ocr_blocks: List[OCRBlock],
    table_bbox: GeometryBox,
    y_margin: float = 5.0,
) -> FooterExtractionResult:
    """
    Extract label→value pairs from OCR blocks below the item table.

    Parameters
    ----------
    ocr_blocks : list[OCRBlock]
        All normalised OCR blocks for the document.
    table_bbox : GeometryBox
        Bounding box of the main item table.
    y_margin : float
        Small margin above table bottom edge to include border-straddling blocks.

    Returns
    -------
    FooterExtractionResult
    """
    result = FooterExtractionResult()

    if not ocr_blocks or not table_bbox:
        return result

    # Filter blocks below the table
    cutoff_y = table_bbox.max_y - y_margin
    below_blocks = [
        b for b in ocr_blocks
        if b.normalized_geometry and b.normalized_geometry.center_y > cutoff_y
    ]
    result.block_count_below_table = len(below_blocks)

    if not below_blocks:
        return result

    # Group blocks into lines by y-coordinate
    lines = _group_into_lines(below_blocks)
    result.line_count = len(lines)

    # Scan each line for label→value matches
    seen_labels: set = set()
    for line_blocks in lines:
        line_text = " ".join((b.text or "").strip() for b in line_blocks if (b.text or "").strip())
        if not line_text:
            continue

        for label_name, label_re in _LABEL_PATTERNS:
            if label_name in seen_labels:
                continue
            match = label_re.search(line_text)
            if not match:
                continue

            # Extract the first amount AFTER the label match
            amounts_after = list(_AMOUNT_RE.finditer(line_text, match.end()))

            # If no amount after label, try extracting from the next line (right-aligned value)
            value = None
            raw_text = ""
            if amounts_after:
                raw_text = amounts_after[-1].group(0).strip()  # Take rightmost
                value = _parse_amount(raw_text)
            elif not amounts_after:
                # Sometimes the value is in a block to the right on the same line
                amounts_in_line = list(_AMOUNT_RE.finditer(line_text))
                if amounts_in_line:
                    raw_text = amounts_in_line[-1].group(0).strip()
                    value = _parse_amount(raw_text)

            if value is not None:
                confidence = 0.80
                if abs(match.start()) < 5:
                    confidence += 0.05  # Label at start of line
                if "." in raw_text:
                    confidence += 0.05  # Decimal amount

                result.fields.append(FooterField(
                    label=label_name,
                    value=value,
                    raw_text=line_text,
                    confidence=round(min(0.95, confidence), 3),
                    source_block_ids=[b.id for b in line_blocks if b.id],
                ))
                seen_labels.add(label_name)

    if result.fields:
        logger.info(
            f"[FOOTER KV] Extracted {len(result.fields)} footer fields: "
            f"{[f.label for f in result.fields]}"
        )

    return result


# ─── Helpers ──────────────────────────────────────────────────────────

def _group_into_lines(blocks: List[OCRBlock]) -> List[List[OCRBlock]]:
    """Group blocks into horizontal lines by y-coordinate proximity."""
    if not blocks:
        return []

    sorted_blocks = sorted(
        blocks,
        key=lambda b: (b.normalized_geometry.center_y, b.normalized_geometry.min_x),
    )

    heights = [b.normalized_geometry.max_y - b.normalized_geometry.min_y for b in sorted_blocks]
    import statistics as _stats
    med_h = _stats.median(heights) if heights else 15.0
    tolerance = max(5.0, med_h * 0.6)

    lines: List[List[OCRBlock]] = []
    current_line: List[OCRBlock] = [sorted_blocks[0]]
    current_y = sorted_blocks[0].normalized_geometry.center_y

    for b in sorted_blocks[1:]:
        by = b.normalized_geometry.center_y
        if abs(by - current_y) <= tolerance:
            current_line.append(b)
        else:
            # Sort line left-to-right before appending
            current_line.sort(key=lambda x: x.normalized_geometry.min_x)
            lines.append(current_line)
            current_line = [b]
            current_y = by

    if current_line:
        current_line.sort(key=lambda x: x.normalized_geometry.min_x)
        lines.append(current_line)

    return lines


def _parse_amount(token: str) -> Optional[float]:
    """Parse a raw amount token into a float."""
    cleaned = re.sub(r"(?i)\b(Rs|INR)\.?", "", token)
    cleaned = cleaned.replace("₹", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None
