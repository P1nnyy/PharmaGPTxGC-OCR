import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from models.layout_models import ColumnRegion, GeometryBox, OCRBlock, RegionType, RowRegion, TableCell, TableRegion


PRODUCT_MARKER_RE = re.compile(
    r"\b(TAB(?:S)?|CAP(?:S)?|INJ|SYP|SYRUP|SUSP|DROPS?|CREAM|OINT|GEL|"
    r"LOTION|SOLUTION|SOAP|ML|MG|GM|MCG|DT|XR|SR|MR)\b",
    re.IGNORECASE,
)
FOOTER_LABEL_RE = re.compile(
    r"\b(SUB\s*TOTAL|GRAND\s*TOTAL|TOTAL|ROUND\s*OFF|ROUNDOFF|DISCOUNT|LESS|"
    r"CGST|SGST|IGST|GST\s*SUMMARY|TAXABLE|AUTHORI[ZS]ED|SIGNATORY|NET\s*(?:AMT|AMOUNT|PAYABLE))\b",
    re.IGNORECASE,
)
META_LABEL_RE = re.compile(
    r"\b(INVOICE|DATE|GSTIN|GST\s+NO|PHONE|TERMS|CONDITIONS|ADDRESS|FOOD\s+LIC|"
    r"D\.?L\.?\s*NO|TRANSPORT|BANK|IFSC|ACCOUNT)\b",
    re.IGNORECASE,
)
HEADER_ONLY_RE = re.compile(
    r"^\s*(?:PRODUCT\s*NAME|PRODUCT|ITEM|BATCH|EXP(?:IRY)?|HSN|MRP|RATE|QTY|AMOUNT|VALUE)\s*$",
    re.IGNORECASE,
)
ALPHA_RE = re.compile(r"[A-Za-z]{3,}")
HSN_RE = re.compile(r"\b\d{6,8}\b")
EXPIRY_RE = re.compile(r"\b\d{1,2}[/-]\d{2,4}\b")
BATCH_RE = re.compile(r"\b(?=[A-Z0-9-]{5,20}\b)(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9-]+\b")


def _geom(block: OCRBlock) -> Optional[GeometryBox]:
    return block.normalized_geometry or block.original_geometry


def _bbox(geometries: List[GeometryBox]) -> GeometryBox:
    min_x = min(g.min_x for g in geometries)
    max_x = max(g.max_x for g in geometries)
    min_y = min(g.min_y for g in geometries)
    max_y = max(g.max_y for g in geometries)
    return GeometryBox(
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
        center_x=(min_x + max_x) / 2.0,
        center_y=(min_y + max_y) / 2.0,
    )


def _synthetic_box(col_index: int, row_index: int, col_count: int) -> GeometryBox:
    col_width = 1000.0 / max(1, col_count)
    row_height = 24.0
    min_x = col_index * col_width
    max_x = min_x + col_width
    min_y = row_index * row_height
    max_y = min_y + row_height
    return GeometryBox(
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
        center_x=(min_x + max_x) / 2.0,
        center_y=(min_y + max_y) / 2.0,
    )


def _split_decimal_values(text: str) -> List[str]:
    clean = re.sub(r"[₹$,\s]", "", text or "")
    if not clean:
        return []

    if re.fullmatch(r"\d[\d.]*", clean) and "." in clean:
        values: List[str] = []
        rest = clean
        while rest:
            dot_idx = rest.find(".")
            if dot_idx <= 0 or dot_idx + 2 >= len(rest):
                break
            segment = rest[: dot_idx + 3]
            if re.fullmatch(r"\d+\.\d{2}", segment):
                values.append(segment)
                rest = rest[dot_idx + 3 :]
                continue
            break
        if values and not rest:
            return values

    return re.findall(r"\d+(?:\.\d{2})", clean)


def _to_decimal(value: str) -> Optional[Decimal]:
    try:
        return Decimal(value.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _variance(values: List[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _nonzero_decimal_values(values: List[str]) -> List[str]:
    clean = []
    for value in values:
        decimal_value = _to_decimal(value)
        if decimal_value is not None and decimal_value > 0:
            clean.append(value)
    return clean


def _split_integer_values(text: str) -> List[str]:
    clean = re.sub(r"[,\s]", "", text or "")
    if not clean or "." in clean or "/" in clean or "-" in clean:
        return []
    return re.findall(r"\d{1,3}", clean)


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _is_product_like_text(text: str) -> bool:
    stripped = (text or "").strip()
    upper = stripped.upper()
    if not stripped or HEADER_ONLY_RE.search(upper) or FOOTER_LABEL_RE.search(upper) or META_LABEL_RE.search(upper):
        return False
    alpha_words = ALPHA_RE.findall(stripped)
    if not alpha_words:
        return False
    if PRODUCT_MARKER_RE.search(stripped):
        return True
    return len(alpha_words) >= 2 and sum(len(word) for word in alpha_words) >= 8


def _is_footer_or_summary_region(region: TableRegion) -> bool:
    text = " ".join(c.text for c in region.cells if c.text).upper()
    if not text:
        return False
    product_hits = len(PRODUCT_MARKER_RE.findall(text))
    footer_hits = len(FOOTER_LABEL_RE.findall(text))
    return footer_hits >= 2 and product_hits < 3


def _excluded_source_block_ids(table_regions: List[TableRegion]) -> set:
    excluded = set()
    for region in table_regions:
        if not _is_footer_or_summary_region(region):
            continue
        for cell in region.cells:
            excluded.update(cell.mapped_block_ids)
    return excluded


def _money_entries(blocks: List[OCRBlock], excluded_ids: set) -> List[Dict[str, Any]]:
    entries = []
    for block in blocks:
        if block.id in excluded_ids:
            continue
        text = block.text or ""
        if FOOTER_LABEL_RE.search(text) or META_LABEL_RE.search(text):
            continue
        values = _split_decimal_values(text)
        if not values:
            continue
        geom = _geom(block)
        if not geom:
            continue
        entries.append({
            "block": block,
            "block_id": block.id,
            "values": values,
            "count": len(values),
            "geometry": geom,
        })
    return entries


def _looks_like_amount_band(values: List[str]) -> bool:
    decimals = [_to_decimal(value) for value in values]
    decimals = [value for value in decimals if value is not None]
    if len(decimals) < 3:
        return False
    non_zero = [value for value in decimals if value > 0]
    if len(non_zero) < 3:
        return False
    high_value_count = sum(1 for value in non_zero if value >= Decimal("20.00"))
    avg_value = sum(non_zero) / len(non_zero)
    return high_value_count >= 3 and avg_value >= Decimal("25.00")


def _is_repeated_gst_rate_band(values: List[str]) -> bool:
    decimals = [_to_decimal(value) for value in values]
    decimals = [value.copy_abs() for value in decimals if value is not None and value > 0]
    if len(decimals) < 3:
        return False
    gst_rates = {Decimal("2.50"), Decimal("5.00"), Decimal("6.00"), Decimal("9.00"), Decimal("12.00"), Decimal("18.00"), Decimal("28.00")}
    rate_hits = sum(1 for value in decimals if value.quantize(Decimal("0.01")) in gst_rates)
    return (rate_hits / len(decimals)) >= 0.55


def _numeric_band_diag(
    band: Dict[str, Any],
    row_count: int,
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    values = band.get("values", [])
    block_right_edges = band.get("block_right_edges", [])
    return {
        "support_count": len(values),
        "right_edge_variance": round(_variance([float(edge) for edge in block_right_edges]), 3),
        "row_coverage": round(min(len(values), row_count) / max(1, row_count), 3),
        "sample_values": values[:6],
        "rejection_reason": rejection_reason,
    }


def _numeric_band_from_entry(entry: Dict[str, Any], band_id: str) -> Dict[str, Any]:
    geom = entry["geometry"]
    return {
        "band_id": band_id,
        "block_ids": [entry["block_id"]],
        "values": entry["values"],
        "geometry": geom,
        "center_x": float(geom.center_x),
        "center_y": float(geom.center_y),
        "block_right_edges": [float(geom.max_x)],
        "source": "fused_decimal_block",
    }


def _horizontal_numeric_bands(blocks: List[OCRBlock], excluded_ids: set) -> List[Dict[str, Any]]:
    numeric_blocks = []
    for block in blocks:
        if block.id in excluded_ids:
            continue
        text = block.text or ""
        if FOOTER_LABEL_RE.search(text) or META_LABEL_RE.search(text):
            continue
        values = _split_decimal_values(text)
        if not values:
            continue
        geom = _geom(block)
        if not geom:
            continue
        numeric_blocks.append((block, values, geom))

    clusters: List[List[Tuple[OCRBlock, List[str], GeometryBox]]] = []
    for item in sorted(numeric_blocks, key=lambda entry: entry[2].center_y):
        geom = item[2]
        for cluster in clusters:
            centers = [entry[2].center_y for entry in cluster]
            if centers and abs(geom.center_y - (sum(centers) / len(centers))) <= 16.0:
                cluster.append(item)
                break
        else:
            clusters.append([item])

    bands = []
    for idx, cluster in enumerate(clusters):
        cluster = sorted(cluster, key=lambda entry: entry[2].min_x)
        values: List[str] = []
        block_ids: List[str] = []
        right_edges: List[float] = []
        geoms: List[GeometryBox] = []
        for block, block_values, geom in cluster:
            nonzero_values = _nonzero_decimal_values(block_values)
            if not nonzero_values:
                continue
            values.extend(nonzero_values)
            block_ids.append(block.id)
            right_edges.append(float(geom.max_x))
            geoms.append(geom)
        if len(values) < 3 or not geoms:
            continue
        geom = _bbox(geoms)
        bands.append({
            "band_id": f"horizontal_numeric_band_{idx}",
            "block_ids": block_ids,
            "values": values,
            "geometry": geom,
            "center_x": float(geom.center_x),
            "center_y": float(geom.center_y),
            "block_right_edges": right_edges,
            "source": "horizontal_decimal_cluster",
        })
    return bands


def _quantity_band_candidates(blocks: List[OCRBlock], excluded_ids: set) -> List[Dict[str, Any]]:
    candidates = []
    for idx, block in enumerate(blocks):
        if block.id in excluded_ids:
            continue
        text = block.text or ""
        if FOOTER_LABEL_RE.search(text) or META_LABEL_RE.search(text):
            continue
        if ALPHA_RE.search(text):
            continue
        if HSN_RE.search(text) or EXPIRY_RE.search(text) or BATCH_RE.search(text):
            continue
        values = _split_integer_values(text)
        if len(values) < 3:
            continue
        integers = [int(value) for value in values if value.isdigit()]
        if len(integers) < 3 or any(value > 500 for value in integers):
            continue
        geom = _geom(block)
        if not geom:
            continue
        candidates.append({
            "band_id": f"quantity_band_{idx}",
            "block_ids": [block.id],
            "values": values,
            "geometry": geom,
            "center_x": float(geom.center_x),
            "center_y": float(geom.center_y),
            "block_right_edges": [float(geom.max_x)],
            "source": "integer_quantity_block",
        })
    return candidates


def _optional_rescue_bands(
    blocks: List[OCRBlock],
    excluded_ids: set,
    product_band: List[OCRBlock],
    amount_band: Dict[str, Any],
    row_count: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    diagnostics: Dict[str, Dict[str, Any]] = {}
    amount_geom = amount_band["geometry"]
    product_geoms = [_geom(block) for block in product_band if _geom(block)]
    product_center_y = _median([float(geom.center_y) for geom in product_geoms])
    amount_center_x = float(amount_geom.center_x)
    amount_values = amount_band["values"][:row_count]
    diagnostics["amount"] = _numeric_band_diag(
        {
            "values": amount_values,
            "block_right_edges": [float(amount_geom.max_x)],
        },
        row_count,
    )

    # Optional numeric bands are block-local: clean numeric-only blocks can be
    # useful even when an earlier broad region grouped them near footer labels.
    band_excluded_ids = set()
    fused_bands = [
        _numeric_band_from_entry(entry, f"fused_money_band_{idx}")
        for idx, entry in enumerate(_money_entries(blocks, band_excluded_ids))
        if entry["block_id"] != amount_band["block_id"]
    ]
    candidate_bands = fused_bands + _horizontal_numeric_bands(blocks, band_excluded_ids)

    accepted_quantity_bands = []
    for band in _quantity_band_candidates(blocks, band_excluded_ids):
        values = band["values"]
        row_coverage = min(len(values), row_count) / max(1, row_count)
        rejection_reason = None
        if band["center_y"] <= product_center_y - 20.0:
            rejection_reason = "above_product_band"
        elif band["center_y"] >= amount_geom.center_y - 24.0:
            rejection_reason = "not_before_amount_band"
        elif abs(band["center_x"] - amount_center_x) > 260.0:
            rejection_reason = "x_band_not_plausibly_aligned"
        elif row_coverage < 0.75:
            rejection_reason = "row_coverage_below_threshold"

        diagnostics[band["band_id"]] = _numeric_band_diag(band, row_count, rejection_reason)
        if not rejection_reason:
            accepted_quantity_bands.append(band)

    accepted_money_bands = []
    for band in sorted(candidate_bands, key=lambda item: item["center_y"]):
        values = band["values"]
        diag_key = band["band_id"]
        row_coverage = min(len(values), row_count) / max(1, row_count)
        decimals = [_to_decimal(value) for value in values]
        decimals = [value for value in decimals if value is not None and value > 0]
        avg_value = sum(decimals) / len(decimals) if decimals else Decimal("0")
        right_edge_variance = _variance([float(edge) for edge in band.get("block_right_edges", [])])

        rejection_reason = None
        if band["center_y"] <= product_center_y - 20.0:
            rejection_reason = "above_product_band"
        elif band["center_y"] >= amount_geom.center_y - 24.0:
            rejection_reason = "not_before_amount_band"
        elif abs(band["center_x"] - amount_center_x) > 170.0:
            rejection_reason = "x_band_not_aligned_with_amount_band"
        elif right_edge_variance > 4500.0:
            rejection_reason = "right_edge_variance_too_high"
        elif row_coverage < 0.75:
            rejection_reason = "row_coverage_below_threshold"
        elif _is_repeated_gst_rate_band(values):
            rejection_reason = "repeated_gst_rate_band"
        elif avg_value < Decimal("20.00"):
            rejection_reason = "average_value_too_low_for_mrp_rate"

        diagnostics[diag_key] = _numeric_band_diag(band, row_count, rejection_reason)
        if rejection_reason:
            continue
        accepted_money_bands.append(band)

    selected_money_bands = []
    selected_block_ids = set()
    for band in accepted_money_bands:
        block_ids = set(band.get("block_ids", []))
        if selected_block_ids.intersection(block_ids):
            diagnostics[band["band_id"]] = _numeric_band_diag(band, row_count, "duplicate_selected_block_ids")
            continue
        selected_money_bands.append(band)
        selected_block_ids.update(block_ids)
        if len(selected_money_bands) == 2:
            break
    supplemental = []
    if accepted_quantity_bands:
        supplemental.append({"col_id": "rescue_quantity", "role": "quantity", **accepted_quantity_bands[0]})
    else:
        diagnostics["quantity"] = {
            "support_count": 0,
            "right_edge_variance": 0.0,
            "row_coverage": 0.0,
            "sample_values": [],
            "rejection_reason": "no_strong_quantity_band",
        }
    if len(selected_money_bands) >= 2:
        supplemental.append({"col_id": "rescue_mrp", "role": "mrp", **selected_money_bands[0]})
        supplemental.append({"col_id": "rescue_rate", "role": "rate", **selected_money_bands[1]})
    elif len(selected_money_bands) == 1:
        supplemental.append({"col_id": "rescue_rate", "role": "rate", **selected_money_bands[0]})

    return supplemental, diagnostics


def _product_blocks_for_money_band(blocks: List[OCRBlock], money_band: Dict[str, Any], excluded_ids: set) -> List[OCRBlock]:
    money_geom = money_band["geometry"]
    x_min = money_geom.min_x - 80.0
    x_max = money_geom.max_x + 80.0
    candidates = []
    for block in blocks:
        if block.id in excluded_ids or block.id == money_band["block_id"]:
            continue
        geom = _geom(block)
        if not geom or geom.center_y >= money_geom.center_y - 20.0:
            continue
        if geom.center_x < x_min or geom.center_x > x_max:
            continue
        if _is_product_like_text(block.text):
            candidates.append(block)

    if not candidates:
        return []

    clusters: List[List[OCRBlock]] = []
    for block in sorted(candidates, key=lambda b: (_geom(b).center_y, _geom(b).center_x)):
        geom = _geom(block)
        for cluster in clusters:
            centers = [_geom(item).center_y for item in cluster if _geom(item)]
            if centers and abs(geom.center_y - (sum(centers) / len(centers))) <= 85.0:
                cluster.append(block)
                break
        else:
            clusters.append([block])

    def cluster_score(cluster: List[OCRBlock]) -> Tuple[int, int, float]:
        marker_hits = sum(1 for item in cluster if PRODUCT_MARKER_RE.search(item.text or ""))
        width = max(_geom(item).center_x for item in cluster) - min(_geom(item).center_x for item in cluster)
        return marker_hits, len(cluster), width

    best = max(clusters, key=cluster_score)
    return sorted(best, key=lambda b: _geom(b).center_x)


def _compatible_count(left: int, right: int) -> bool:
    if left < 3 or right < 3:
        return False
    return abs(left - right) <= max(2, int(max(left, right) * 0.35))


def _medicine_candidate_has_amount_column(region: TableRegion) -> bool:
    if region.region_type != RegionType.MEDICINE_TABLE:
        return False
    cells_by_row: Dict[str, List[TableCell]] = {}
    for cell in region.cells:
        cells_by_row.setdefault(cell.row_id, []).append(cell)

    item_like_row_ids = set()
    for row in region.rows:
        row_text = " ".join(c.text for c in cells_by_row.get(row.row_id, []) if c.text)
        if _is_product_like_text(row_text) and _split_decimal_values(row_text):
            item_like_row_ids.add(row.row_id)
    if len(item_like_row_ids) < 2:
        return False

    money_by_col: Dict[str, int] = {}
    for cell in region.cells:
        if cell.row_id in item_like_row_ids and _split_decimal_values(cell.text):
            money_by_col[cell.col_id] = money_by_col.get(cell.col_id, 0) + 1
    return any(count >= 2 for count in money_by_col.values())


def _column_band_metrics() -> Dict[str, Any]:
    return {
        "column_band_rescue_attempted": False,
        "column_band_rescue_success": False,
        "column_band_rescue_selected": False,
        "column_band_rescue_reason": None,
        "column_band_rescued_rows_count": 0,
        "column_band_rescue_confidence": 0.0,
        "column_band_rescue_rejected_reason": None,
        "column_band_rescue_band_counts": {},
        "column_band_rescue_band_diagnostics": {},
        "column_band_rescue_item_subtotal_preview": 0.0,
    }


def build_column_band_rescue_candidate(
    ocr_blocks: List[OCRBlock],
    table_regions: List[TableRegion],
    selected_main_table: TableRegion,
    selected_main_item_rows_count: int,
    max_final_column_count: int,
) -> Tuple[Optional[TableRegion], Dict[str, Any]]:
    metrics = _column_band_metrics()

    if selected_main_item_rows_count > 0:
        metrics["column_band_rescue_rejected_reason"] = "main_table_has_item_rows"
        return None, metrics
    if max_final_column_count > 4:
        metrics["column_band_rescue_rejected_reason"] = "max_final_column_count_gt_4"
        return None, metrics
    if any(_medicine_candidate_has_amount_column(region) for region in table_regions):
        metrics["column_band_rescue_rejected_reason"] = "existing_medicine_candidate_has_amount_column"
        return None, metrics

    excluded_ids = _excluded_source_block_ids(table_regions)
    all_money_bands = [entry for entry in _money_entries(ocr_blocks, excluded_ids) if entry["count"] >= 3]
    money_bands = [entry for entry in all_money_bands if _looks_like_amount_band(entry["values"])]
    product_like_blocks = [
        block for block in ocr_blocks
        if block.id not in excluded_ids and _is_product_like_text(block.text) and _geom(block)
    ]
    metrics["column_band_rescue_band_counts"] = {
        "product_like_blocks": len(product_like_blocks),
        "money_like_blocks": len(all_money_bands),
        "money_like_values": sum(entry["count"] for entry in all_money_bands),
        "amount_like_money_bands": len(money_bands),
    }

    if len(product_like_blocks) < 3:
        metrics["column_band_rescue_rejected_reason"] = "fewer_than_3_product_like_blocks"
        return None, metrics
    if sum(entry["count"] for entry in money_bands) < 3:
        metrics["column_band_rescue_rejected_reason"] = "fewer_than_3_money_like_values"
        return None, metrics

    metrics["column_band_rescue_attempted"] = True
    metrics["column_band_rescue_reason"] = "collapsed_low_column_table_with_product_and_money_bands"

    band_options = []
    for money_band in money_bands:
        products = _product_blocks_for_money_band(ocr_blocks, money_band, excluded_ids)
        if not _compatible_count(len(products), money_band["count"]):
            continue
        count_delta = abs(len(products) - money_band["count"])
        marker_hits = sum(1 for block in products if PRODUCT_MARKER_RE.search(block.text or ""))
        band_options.append((marker_hits, -count_delta, money_band["geometry"].center_y, products, money_band))

    if not band_options:
        metrics["column_band_rescue_rejected_reason"] = "no_compatible_product_money_band_counts"
        return None, metrics

    _, _, _, product_band, amount_band = max(band_options, key=lambda item: item[:3])
    row_count = min(len(product_band), amount_band["count"])
    if row_count < 3:
        metrics["column_band_rescue_rejected_reason"] = "rescued_rows_lt_3"
        return None, metrics

    amount_values = amount_band["values"][:row_count]
    subtotal = sum((_to_decimal(value) or Decimal("0.00")) for value in amount_values)
    if subtotal <= 0:
        metrics["column_band_rescue_rejected_reason"] = "item_subtotal_preview_not_positive"
        return None, metrics

    supplemental_bands, band_diagnostics = _optional_rescue_bands(
        ocr_blocks,
        excluded_ids,
        product_band,
        amount_band,
        row_count,
    )
    metrics["column_band_rescue_band_diagnostics"] = band_diagnostics

    column_specs = [
        {"col_id": "rescue_product", "role": "product"},
        *supplemental_bands,
        {"col_id": "rescue_amount", "role": "amount", **amount_band},
    ]
    col_count = len(column_specs)
    columns = [
        ColumnRegion(col_id=spec["col_id"], geometry=_synthetic_box(col_idx, 0, col_count), confidence=0.9)
        for col_idx, spec in enumerate(column_specs)
    ]
    rows: List[RowRegion] = []
    cells: List[TableCell] = []
    source_band_ids = [amount_band["block_id"], *[block_id for band in supplemental_bands for block_id in band.get("block_ids", [])]]

    for idx in range(row_count):
        product_block = product_band[idx]
        product_geom = _geom(product_block)
        amount_geom = amount_band["geometry"]
        supplemental_geoms = [band["geometry"] for band in supplemental_bands if band.get("geometry")]
        row_geom = _bbox([product_geom, amount_geom, *supplemental_geoms])
        source_block_ids = [product_block.id, amount_band["block_id"], *[block_id for band in supplemental_bands for block_id in band.get("block_ids", [])]]
        alignment_confidence = max(0.5, 1.0 - (abs(len(product_band) - amount_band["count"]) / max(len(product_band), amount_band["count"])))
        row = RowRegion(
            row_id=f"column_band_rescue_row_{idx}",
            geometry=row_geom,
            confidence=alignment_confidence,
            stability=alignment_confidence,
            assigned_token_count=len(source_block_ids),
            row_role="item_row",
            provenance={
                "rescue_reason": metrics["column_band_rescue_reason"],
                "source_band_ids": source_band_ids,
                "source_block_ids": source_block_ids,
                "alignment_confidence": round(alignment_confidence, 3),
            },
        )
        rows.append(row)
        cells.append(TableCell(
            row_id=row.row_id,
            col_id="rescue_product",
            geometry=_synthetic_box(0, idx, col_count),
            confidence=alignment_confidence,
            mapped_block_ids=[product_block.id],
            text=product_block.text,
            original_text=product_block.text,
            assignment_confidence=alignment_confidence,
            assignment_strategy="column_band_rescue",
        ))
        for col_idx, band in enumerate(supplemental_bands, start=1):
            band_values = band.get("values", [])
            if idx >= len(band_values):
                continue
            cells.append(TableCell(
                row_id=row.row_id,
                col_id=band["col_id"],
                geometry=_synthetic_box(col_idx, idx, col_count),
                confidence=alignment_confidence,
                mapped_block_ids=band.get("block_ids", []),
                text=band_values[idx],
                original_text=band_values[idx],
                assignment_confidence=alignment_confidence,
                assignment_strategy="column_band_rescue",
            ))
        cells.append(TableCell(
            row_id=row.row_id,
            col_id="rescue_amount",
            geometry=_synthetic_box(col_count - 1, idx, col_count),
            confidence=alignment_confidence,
            mapped_block_ids=[amount_band["block_id"]],
            text=amount_values[idx],
            original_text=amount_values[idx],
            assignment_confidence=alignment_confidence,
            assignment_strategy="column_band_rescue",
        ))

    if any(FOOTER_LABEL_RE.search(c.text or "") for c in cells):
        metrics["column_band_rescue_rejected_reason"] = "footer_label_inside_rescued_rows"
        return None, metrics

    confidence = min(0.95, 0.48 + (row_count * 0.055) + (0.12 if abs(len(product_band) - amount_band["count"]) <= 1 else 0.06))
    candidate = TableRegion(
        table_id="column_band_rescue_candidate",
        region_type=RegionType.MEDICINE_TABLE,
        geometry=_bbox([row.geometry for row in rows if row.geometry]),
        rows=rows,
        columns=columns,
        cells=cells,
        confidence=round(confidence, 3),
        topology_confidence=round(confidence, 3),
        source_engine="column_band_rescue",
    )

    metrics["column_band_rescue_success"] = True
    metrics["column_band_rescued_rows_count"] = row_count
    metrics["column_band_rescue_confidence"] = round(confidence, 3)
    metrics["column_band_rescue_item_subtotal_preview"] = float(round(subtotal, 2))
    metrics["column_band_rescue_band_counts"].update({
        "selected_product_band_blocks": len(product_band),
        "selected_amount_band_values": amount_band["count"],
        "selected_supplemental_bands": [band["role"] for band in supplemental_bands],
    })
    return candidate, metrics
