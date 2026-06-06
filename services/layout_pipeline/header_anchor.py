"""
Header Anchor — Generic column-header detection for wide pharma tables.

Scans rows in the top region of a table for short column-label tokens
matching pharma header patterns, then derives column bands from header
token x-positions.  These bands are used downstream to:
  1. Guide spanning-OCR-block splitting.
  2. Provide explicit ``header_row`` roles for semantic classification.

All detection is pattern-based and vendor-agnostic.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.logger import logger
from models.layout_models import OCRBlock, TableRegion, GeometryBox


# Generic pharma column header labels (case-insensitive).
_LABEL_RE = re.compile(
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
    r"|PACK|COMPANY|MFR"
    r"|SR\.?\s*NO|S\.?\s*NO|SL\.?\s*NO|NO"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class ColumnBand:
    """A column band derived from header token x-position."""
    min_x: float
    max_x: float
    label: str = ""


@dataclass
class HeaderAnchorResult:
    """Result of header-row detection."""
    attached: bool = False
    header_row_ids: List[str] = field(default_factory=list)
    column_bands: List[ColumnBand] = field(default_factory=list)
    signals: Dict[str, Any] = field(default_factory=dict)


def detect_header_row(
    blocks: List[OCRBlock],
    table_region: TableRegion,
) -> HeaderAnchorResult:
    """
    Detect column-header rows in the top region of a table.

    Scans the first 1-3 rows (by y-coordinate) for short label-like
    tokens matching pharma header patterns.  Returns column bands for
    downstream block splitting and header row ids for role assignment.

    Parameters
    ----------
    blocks : list[OCRBlock]
        All OCR blocks in the document.
    table_region : TableRegion
        The selected main table region.

    Returns
    -------
    HeaderAnchorResult
    """
    result = HeaderAnchorResult()

    if not table_region.rows or not table_region.cells:
        return result

    # Use table geometry to establish vertical reference
    table_geom = table_region.geometry or table_region.normalized_geometry
    if not table_geom:
        return result

    # Identify the top rows (by min_y ascending)
    sorted_rows = sorted(
        table_region.rows,
        key=lambda r: r.geometry.min_y if r.geometry else 0,
    )

    # Scan at most the first 3 rows for header labels
    candidate_rows = sorted_rows[:3]

    for row in candidate_rows:
        # Collect cells in this row
        row_cells = [c for c in table_region.cells if c.row_id == row.row_id]
        if not row_cells:
            continue

        # Count label matches in this row
        label_count = 0
        band_tokens: List[Tuple[float, float, str]] = []  # (min_x, max_x, label)

        for cell in row_cells:
            text = (cell.text or "").strip()
            if not text or len(text) > 30:
                continue
            matches = _LABEL_RE.findall(text)
            if matches:
                label_count += len(matches)
                geom = cell.geometry or cell.normalized_geometry
                if geom:
                    band_tokens.append((geom.min_x, geom.max_x, text))

        # A row qualifies as a header if it has ≥4 distinct label tokens
        if label_count >= 4:
            result.attached = True
            result.header_row_ids.append(row.row_id)
            result.signals[row.row_id] = {
                "label_count": label_count,
                "band_token_count": len(band_tokens),
            }

            # Derive column bands from header token positions
            for min_x, max_x, label in band_tokens:
                result.column_bands.append(ColumnBand(
                    min_x=min_x,
                    max_x=max_x,
                    label=label,
                ))

    # Sort column bands left-to-right
    result.column_bands.sort(key=lambda b: b.min_x)

    if result.attached:
        logger.info(
            f"[HEADER ANCHOR] Detected {len(result.header_row_ids)} header row(s) "
            f"with {len(result.column_bands)} column bands"
        )

    return result
