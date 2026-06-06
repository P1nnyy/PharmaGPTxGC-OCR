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
from models.layout_models import OCRBlock, TableRegion, GeometryBox, ColumnRegion, TableCell


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


@dataclass
class _HeaderAnchor:
    """Internal token/phrase anchor before conversion to full column bands."""
    min_x: float
    max_x: float
    label: str

    @property
    def center_x(self) -> float:
        return (self.min_x + self.max_x) / 2.0


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


def derive_header_column_bands(
    blocks: List[OCRBlock],
    table_min_x: Optional[float] = None,
    table_max_x: Optional[float] = None,
) -> List[ColumnBand]:
    """
    Derive individual wide-table column bands from header OCR blocks.

    This deliberately works from OCR geometry, not existing TSR cells, so a
    grouped TSR header like ``"HSN CODE PACK CMPNY BATCH NO"`` can expand into
    separate HSN, PACK, COMPANY, and BATCH anchors. It also merges stacked
    header fragments in the same x-band, e.g. OLD + MRP -> OLD_MRP.
    """
    anchors = _extract_header_anchors(blocks)
    anchors = _combine_stacked_header_fragments(anchors)
    anchors = _dedupe_repeated_labels(anchors)
    if not anchors:
        return []

    anchors.sort(key=lambda a: a.center_x)

    min_x = table_min_x
    max_x = table_max_x
    valid_geoms = [b.normalized_geometry for b in blocks if b.normalized_geometry]
    if min_x is None and valid_geoms:
        min_x = min(g.min_x for g in valid_geoms)
    if max_x is None and valid_geoms:
        max_x = max(g.max_x for g in valid_geoms)

    if min_x is None:
        min_x = anchors[0].min_x
    if max_x is None:
        max_x = anchors[-1].max_x

    anchors = _insert_inferred_product_anchor(anchors, min_x)
    anchors.sort(key=lambda a: a.center_x)

    bands: List[ColumnBand] = []
    for index, anchor in enumerate(anchors):
        if index == 0:
            band_min = float(min_x)
        else:
            band_min = (anchors[index - 1].center_x + anchor.center_x) / 2.0

        if index == len(anchors) - 1:
            band_max = float(max_x)
        else:
            band_max = (anchor.center_x + anchors[index + 1].center_x) / 2.0

        if band_max <= band_min:
            continue
        bands.append(ColumnBand(min_x=band_min, max_x=band_max, label=anchor.label))

    return bands


def expand_table_columns_from_header(
    table_region: TableRegion,
    blocks: List[OCRBlock],
    min_columns: int = 10,
) -> Dict[str, Any]:
    """
    Rebuild collapsed wide-table columns/cells from header-derived bands.

    Returns diagnostic metadata and mutates ``table_region`` only when expansion
    succeeds with at least ``min_columns`` bands.
    """
    current_count = len(table_region.columns)
    table_geom = table_region.geometry or table_region.normalized_geometry
    if not table_region.rows or not table_geom:
        return {
            "expanded": False,
            "reason": "missing_table_geometry_or_rows",
            "current_column_count": current_count,
        }

    header_blocks = _select_header_candidate_blocks(blocks, table_region)
    bands = derive_header_column_bands(
        header_blocks,
        table_min_x=table_geom.min_x,
        table_max_x=table_geom.max_x,
    )

    diagnostics = {
        "expanded": False,
        "current_column_count": current_count,
        "header_block_count": len(header_blocks),
        "derived_column_count": len(bands),
        "derived_labels": [b.label for b in bands],
    }

    if len(bands) < min_columns:
        diagnostics["reason"] = "insufficient_header_column_expansion"
        return diagnostics

    if len(bands) <= current_count:
        diagnostics["reason"] = "header_expansion_not_larger_than_current"
        return diagnostics

    table_region.columns = [
        ColumnRegion(
            col_id=f"col_{idx}",
            geometry=GeometryBox(
                min_x=band.min_x,
                max_x=band.max_x,
                min_y=table_geom.min_y,
                max_y=table_geom.max_y,
                center_x=(band.min_x + band.max_x) / 2.0,
                center_y=(table_geom.min_y + table_geom.max_y) / 2.0,
            ),
            normalized_geometry=GeometryBox(
                min_x=band.min_x,
                max_x=band.max_x,
                min_y=table_geom.min_y,
                max_y=table_geom.max_y,
                center_x=(band.min_x + band.max_x) / 2.0,
                center_y=(table_geom.min_y + table_geom.max_y) / 2.0,
            ),
            confidence=1.0,
        )
        for idx, band in enumerate(bands)
    ]

    rebuilt_cells: List[TableCell] = []
    for row in table_region.rows:
        row_geom = row.geometry or row.normalized_geometry
        if not row_geom:
            continue
        for col in table_region.columns:
            col_geom = col.geometry or col.normalized_geometry
            if not col_geom:
                continue
            cell_geom = GeometryBox(
                min_x=col_geom.min_x,
                max_x=col_geom.max_x,
                min_y=row_geom.min_y,
                max_y=row_geom.max_y,
                center_x=(col_geom.min_x + col_geom.max_x) / 2.0,
                center_y=(row_geom.min_y + row_geom.max_y) / 2.0,
            )
            rebuilt_cells.append(TableCell(
                row_id=row.row_id,
                col_id=col.col_id,
                geometry=cell_geom,
                normalized_geometry=cell_geom,
                confidence=1.0,
            ))

    table_region.cells = rebuilt_cells
    diagnostics["expanded"] = True
    diagnostics["reason"] = "header_column_expansion_applied"
    diagnostics["final_column_count"] = len(table_region.columns)

    logger.info(
        f"[HEADER ANCHOR] Expanded {table_region.table_id} from "
        f"{current_count} to {len(table_region.columns)} columns via header bands: "
        f"{diagnostics['derived_labels']}"
    )

    return diagnostics


def _select_header_candidate_blocks(blocks: List[OCRBlock], table_region: TableRegion) -> List[OCRBlock]:
    """Select OCR blocks from the top/header rows of a table region."""
    table_geom = table_region.geometry or table_region.normalized_geometry
    if not table_geom:
        return []

    sorted_rows = sorted(
        [r for r in table_region.rows if r.geometry or r.normalized_geometry],
        key=lambda r: (r.geometry or r.normalized_geometry).min_y,
    )
    candidate_rows = sorted_rows[:3]
    if not candidate_rows:
        return []

    selected: List[OCRBlock] = []
    for block in blocks:
        geom = block.normalized_geometry
        if not geom:
            continue
        if geom.max_x < table_geom.min_x or geom.min_x > table_geom.max_x:
            continue
        for row in candidate_rows:
            row_geom = row.geometry or row.normalized_geometry
            if not row_geom:
                continue
            y_overlap = min(geom.max_y, row_geom.max_y) - max(geom.min_y, row_geom.min_y)
            if y_overlap > 0:
                selected.append(block)
                break

    # Prefer rows that actually contain header labels; fallback to all top-row blocks.
    labeled = [b for b in selected if _extract_header_anchors([b])]
    return labeled or selected


def _extract_header_anchors(blocks: List[OCRBlock]) -> List[_HeaderAnchor]:
    anchors: List[_HeaderAnchor] = []
    for block in blocks:
        geom = block.normalized_geometry
        text = (block.text or "").strip()
        if not geom or not text:
            continue

        words = []
        for match in re.finditer(r"\S+", text):
            raw = match.group()
            clean = re.sub(r"^[^\w./%-]+|[^\w./%-]+$", "", raw).upper()
            if clean:
                words.append((clean, match.start(), match.end()))

        consumed = set()

        def span_for(start_char: int, end_char: int) -> Tuple[float, float]:
            total = max(1, len(text))
            min_x = geom.min_x + (start_char / total) * (geom.max_x - geom.min_x)
            max_x = geom.min_x + (end_char / total) * (geom.max_x - geom.min_x)
            return min_x, max_x

        def add(label: str, word_indexes: List[int]) -> None:
            min_char = min(words[i][1] for i in word_indexes)
            max_char = max(words[i][2] for i in word_indexes)
            min_x, max_x = span_for(min_char, max_char)
            anchors.append(_HeaderAnchor(min_x=min_x, max_x=max_x, label=label))
            consumed.update(word_indexes)

        for i, (word, _, _) in enumerate(words):
            if i in consumed:
                continue
            next_word = words[i + 1][0] if i + 1 < len(words) else ""

            if word == "HSN":
                add("HSN_CODE", [i, i + 1] if next_word == "CODE" else [i])
            elif word in {"BATCH", "LOT"}:
                add("BATCH_NO", [i, i + 1] if next_word in {"NO", "NO.", "N0"} else [i])
            elif word == "NEW":
                mrp_idx = _find_nearby_word(words, i, {"MRP"})
                add("NEW_MRP", [i, mrp_idx] if mrp_idx is not None else [i])
            elif word == "OLD":
                mrp_idx = _find_nearby_word(words, i, {"MRP"})
                add("OLD_MRP", [i, mrp_idx] if mrp_idx is not None else [i])

        for i, (word, _, _) in enumerate(words):
            if i in consumed:
                continue
            if word in {"PRODUCT", "ITEM", "DESCRIPTION", "PARTICULARS", "MEDICINE", "DRUG", "NAME"}:
                add("ITEM", [i])
            elif word in {"PACK", "PKG"}:
                add("PACK", [i])
            elif word in {"COMPANY", "CMPNY", "MFR", "MANUFACTURER"}:
                add("CMPNY", [i])
            elif word in {"QTY", "QUANTITY", "BILLED"}:
                add("QTY", [i])
            elif word in {"DISC", "DISCOUNT", "FREE", "SCHEME", "SCH", "TD", "CD"}:
                add("DISC", [i])
            elif word in {"RATE", "PTR", "PRICE"}:
                add("RATE", [i])
            elif word in {"EXP", "EXPIRY"}:
                add("EXP", [i])
            elif word == "MRP":
                add("MRP", [i])
            elif word in {"GST", "GSTW", "CGST", "SGST", "IGST", "TAX"}:
                add("GST", [i])
            elif word in {"AMOUNT", "AMT", "VALUE", "NET"}:
                add("AMOUNT", [i])

    return _dedupe_close_anchors(anchors)


def _find_nearby_word(words: List[Tuple[str, int, int]], index: int, targets: set[str]) -> Optional[int]:
    for offset in range(1, min(4, len(words) - index)):
        if words[index + offset][0] in targets:
            return index + offset
    return None


def _combine_stacked_header_fragments(anchors: List[_HeaderAnchor]) -> List[_HeaderAnchor]:
    combined: List[_HeaderAnchor] = []
    used = set()

    for i, anchor in enumerate(anchors):
        if i in used:
            continue
        if anchor.label in {"OLD_MRP", "NEW_MRP"}:
            combined.append(anchor)
            used.add(i)
            continue

        if anchor.label in {"MRP"}:
            marker_idx = _find_overlapping_anchor(anchors, i, {"OLD_MRP", "NEW_MRP"})
            if marker_idx is not None:
                marker = anchors[marker_idx]
                combined.append(_HeaderAnchor(
                    min_x=min(anchor.min_x, marker.min_x),
                    max_x=max(anchor.max_x, marker.max_x),
                    label=marker.label,
                ))
                used.update({i, marker_idx})
                continue

        combined.append(anchor)
        used.add(i)

    return _dedupe_close_anchors(combined)


def _find_overlapping_anchor(
    anchors: List[_HeaderAnchor],
    source_idx: int,
    labels: set[str],
) -> Optional[int]:
    source = anchors[source_idx]
    source_width = max(1.0, source.max_x - source.min_x)
    for idx, candidate in enumerate(anchors):
        if idx == source_idx or candidate.label not in labels:
            continue
        center_gap = abs(source.center_x - candidate.center_x)
        candidate_width = max(1.0, candidate.max_x - candidate.min_x)
        if center_gap <= max(source_width, candidate_width):
            return idx
    return None


def _dedupe_close_anchors(anchors: List[_HeaderAnchor]) -> List[_HeaderAnchor]:
    deduped: List[_HeaderAnchor] = []
    for anchor in sorted(anchors, key=lambda a: (a.center_x, a.label)):
        duplicate = False
        for existing in deduped:
            if existing.label == anchor.label and abs(existing.center_x - anchor.center_x) <= 8.0:
                existing.min_x = min(existing.min_x, anchor.min_x)
                existing.max_x = max(existing.max_x, anchor.max_x)
                duplicate = True
                break
        if not duplicate:
            deduped.append(anchor)
    return deduped


def _dedupe_repeated_labels(anchors: List[_HeaderAnchor]) -> List[_HeaderAnchor]:
    """Remove repeated canonical labels in one header row while preserving order."""
    seen = set()
    deduped: List[_HeaderAnchor] = []
    for anchor in sorted(anchors, key=lambda a: a.center_x):
        if anchor.label in seen:
            continue
        seen.add(anchor.label)
        deduped.append(anchor)
    return deduped


def _insert_inferred_product_anchor(anchors: List[_HeaderAnchor], table_min_x: float) -> List[_HeaderAnchor]:
    if not anchors:
        return anchors
    labels = {a.label for a in anchors}
    if "ITEM" in labels:
        return anchors

    first = min(anchors, key=lambda a: a.center_x)
    if first.label not in {"HSN_CODE", "PACK", "CMPNY", "BATCH_NO"}:
        return anchors

    first_width = max(20.0, first.max_x - first.min_x)
    inferred_center = max(table_min_x + first_width / 2.0, first.center_x - max(60.0, first_width * 1.5))
    inferred = _HeaderAnchor(
        min_x=max(table_min_x, inferred_center - first_width / 2.0),
        max_x=max(table_min_x + 1.0, inferred_center + first_width / 2.0),
        label="ITEM",
    )
    return [inferred, *anchors]
