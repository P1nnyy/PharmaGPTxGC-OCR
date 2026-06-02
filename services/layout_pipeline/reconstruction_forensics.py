from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


TOKEN_PATHS = ("ocr_blocks", "blocks", "text_blocks", "raw_ocr")
ROW_PATHS = ("structured_rows", "reconstructed_rows", "reconstructed_item_rows", "item_rows", "item_rows_clean")
TABLE_PATHS = ("structured_tables", "table_regions")
DEBUG_PATHS = (
    "layout_debug",
    "reconstruction_debug",
    "metrics.topology_debug",
    "metrics.semantic_debug",
    "metrics.final_column_semantics",
    "metrics.column_semantic_cache",
    "metrics.row_validation",
    "metrics.financial_reconciliation",
    "canonical_invoice",
    "quality_gate",
    "row_math_repair",
    "footer_rescue",
)

NUMERIC_RE = re.compile(r"-?(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?|-?\.\d+")
PRODUCT_RE = re.compile(r"[A-Za-z]{3,}")
FOOTER_RE = re.compile(r"\b(total|subtotal|grand|round|net amount|payable|discount|less|scheme)\b", re.I)
TAX_RE = re.compile(r"\b(cgst|sgst|igst|gst|tax|taxable)\b", re.I)
HEADER_LABELS = {
    "qty": re.compile(r"\b(qty|quantity|pcs|case|free)\b", re.I),
    "rate": re.compile(r"\b(rate|ptr|price)\b", re.I),
    "amount": re.compile(r"\b(amount|value|net|total)\b", re.I),
    "product": re.compile(r"\b(product|item|particular|description|medicine)\b", re.I),
}


def build_reconstruction_forensics(
    raw_result: dict,
    canonical_invoice=None,
    target_products: Optional[List[str]] = None,
) -> dict:
    raw_result = raw_result if isinstance(raw_result, dict) else {}
    target_products = [str(value) for value in (target_products or []) if str(value).strip()]
    schema_paths_found = _schema_paths_found(raw_result)

    canonical = _canonical_dict(canonical_invoice) or raw_result.get("canonical_invoice") or {}
    if not isinstance(canonical, dict):
        canonical = {}

    tokens = _extract_tokens(raw_result)
    rows = _extract_rows(raw_result)
    columns = _extract_columns(raw_result, rows)
    canonical_trace = _extract_canonical_trace(canonical, rows, tokens)

    _mark_canonical_appearances(tokens, canonical)
    footer_leakage_candidates = _footer_leakage(rows)
    semantic_poisoning_candidates = _semantic_poisoning(columns)
    row_grouping_warnings = _row_grouping_warnings(rows)
    target_trace = _target_product_trace(target_products, tokens, rows, canonical_trace)

    summary = _build_summary(
        raw_result=raw_result,
        tokens=tokens,
        rows=rows,
        columns=columns,
        canonical_trace=canonical_trace,
        footer_leakage_candidates=footer_leakage_candidates,
        semantic_poisoning_candidates=semantic_poisoning_candidates,
        row_grouping_warnings=row_grouping_warnings,
    )

    return {
        "invoice_id": _invoice_id(raw_result, canonical),
        "summary": summary,
        "rows": rows,
        "tokens": tokens,
        "columns": columns,
        "canonical_trace": canonical_trace,
        "footer_leakage_candidates": footer_leakage_candidates,
        "semantic_poisoning_candidates": semantic_poisoning_candidates,
        "row_grouping_warnings": row_grouping_warnings,
        "schema_paths_found": schema_paths_found,
        "target_product_trace": target_trace,
    }


def _schema_paths_found(raw_result: dict) -> List[Dict[str, Any]]:
    paths = [*TOKEN_PATHS, *ROW_PATHS, *TABLE_PATHS, *DEBUG_PATHS]
    found = []
    for path in paths:
        value = _get_path(raw_result, path.split("."))
        found.append({
            "path": path,
            "exists": value is not None,
            "type": type(value).__name__ if value is not None else None,
            "count": len(value) if isinstance(value, (list, dict)) else None,
        })
    return found


def _extract_tokens(raw_result: dict) -> List[Dict[str, Any]]:
    tokens = []
    seen = set()

    for path in TOKEN_PATHS:
        for idx, token in enumerate(_as_list(raw_result.get(path))):
            parsed = _token_from_mapping(token, f"{path}[{idx}]", idx)
            if parsed and parsed["token_id"] not in seen:
                seen.add(parsed["token_id"])
                tokens.append(parsed)

    topology_tokens = _get_path(raw_result, ("metrics", "topology_debug", "raw_token_graph"))
    for idx, token in enumerate(_as_list(topology_tokens)):
        parsed = _token_from_mapping(token, f"metrics.topology_debug.raw_token_graph[{idx}]", idx)
        if parsed and parsed["token_id"] not in seen:
            seen.add(parsed["token_id"])
            tokens.append(parsed)

    for table_idx, table in enumerate(_as_list(raw_result.get("structured_tables"))):
        if not isinstance(table, dict):
            continue
        for cell_idx, cell in enumerate(_as_list(table.get("cells"))):
            for token_id in _as_list(cell.get("mapped_block_ids")):
                token_id = str(token_id)
                for token in tokens:
                    if token["token_id"] == token_id:
                        token["assigned_row_id"] = token.get("assigned_row_id") or cell.get("row_id")
                        token["assigned_cell_id"] = token.get("assigned_cell_id") or f"{cell.get('row_id')}:{cell.get('col_id')}"
                        token["assigned_column_id"] = token.get("assigned_column_id") or cell.get("col_id")
                        token["assigned_table_id"] = token.get("assigned_table_id") or table.get("table_id")
                        token["source_path"] = token.get("source_path") or f"structured_tables[{table_idx}].cells[{cell_idx}]"
                        break

    semantic_by_col = _collect_semantics(raw_result)
    for token in tokens:
        table_id = token.get("assigned_table_id")
        col_id = token.get("assigned_column_id") or token.get("assigned_col_id")
        token["semantic_label"] = token.get("semantic_label") or semantic_by_col.get((table_id, col_id)) or semantic_by_col.get((None, col_id))

    return tokens


def _token_from_mapping(value: Any, source_path: str, idx: int) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    text = _clean_text(_first(value, ("text", "raw_text", "label", "value")))
    if not text:
        return None
    geometry = _extract_geometry(value)
    token_id = _first(value, ("token_id", "id", "block_id")) or f"token_{idx}"
    return {
        "token_id": str(token_id),
        "text": text,
        "confidence": _safe_float(_first(value, ("confidence", "score"))),
        **geometry,
        "assigned_row_id": _first(value, ("assigned_row_id", "row_id", "visual_row_id")),
        "assigned_cell_id": _first(value, ("assigned_cell_id", "cell_id")),
        "assigned_column_id": _first(value, ("assigned_column_id", "assigned_col_id", "col_id", "column_id")),
        "semantic_label": _first(value, ("semantic_label", "semantic", "type")),
        "source_path": source_path,
        "appears_in_canonical_fields": [],
    }


def _extract_rows(raw_result: dict) -> List[Dict[str, Any]]:
    rows = []
    seen = set()
    cell_index = _cell_index(raw_result)
    row_math = _row_math_status(raw_result)
    canonical_by_row = _canonical_by_row(raw_result.get("canonical_invoice"))

    for path in ROW_PATHS:
        for idx, row in enumerate(_as_list(raw_result.get(path))):
            parsed = _row_from_mapping(row, f"{path}[{idx}]", idx, cell_index, row_math, canonical_by_row)
            key = (parsed["row_id"], parsed["source_path"])
            if key not in seen:
                rows.append(parsed)
                seen.add(key)

    for table_idx, table in enumerate(_as_list(raw_result.get("structured_tables"))):
        if not isinstance(table, dict):
            continue
        table_id = table.get("table_id")
        for row_idx, row in enumerate(_as_list(table.get("rows"))):
            parsed = _row_from_mapping(
                row,
                f"structured_tables[{table_idx}].rows[{row_idx}]",
                row_idx,
                cell_index,
                row_math,
                canonical_by_row,
                table_id=table_id,
            )
            key = (parsed["row_id"], parsed["source_path"])
            if key not in seen:
                rows.append(parsed)
                seen.add(key)

    topology_tables = _get_path(raw_result, ("metrics", "topology_debug", "main_tables"))
    for table_idx, table in enumerate(_as_list(topology_tables)):
        if not isinstance(table, dict):
            continue
        for row_idx, row in enumerate(_as_list(table.get("rows"))):
            parsed = _row_from_mapping(
                row,
                f"metrics.topology_debug.main_tables[{table_idx}].rows[{row_idx}]",
                row_idx,
                cell_index,
                row_math,
                canonical_by_row,
                table_id=table.get("table_id"),
            )
            key = (parsed["row_id"], parsed["source_path"])
            if key not in seen:
                rows.append(parsed)
                seen.add(key)

    _add_row_context_warnings(rows)
    return rows


def _row_from_mapping(
    value: Any,
    source_path: str,
    idx: int,
    cell_index: Dict[str, List[Dict[str, Any]]],
    row_math: Dict[str, str],
    canonical_by_row: Dict[str, str],
    table_id: Any = None,
) -> Dict[str, Any]:
    row = value if isinstance(value, dict) else {"text": str(value)}
    row_id = str(_first(row, ("row_id", "visual_row_id", "id", "index", "row_index")) or f"row_{idx}")
    blocks = _as_list(row.get("blocks"))
    token_text = " ".join(_clean_text(_first(block, ("text", "raw_text"))) for block in blocks if isinstance(block, dict))
    cells = [dict(cell) for cell in cell_index.get(row_id, [])]
    cell_text = " ".join(_clean_text(cell.get("text")) for cell in cells)
    columns = row.get("columns") if isinstance(row.get("columns"), dict) else {}
    column_text = " ".join(_clean_text(value) for value in columns.values())
    raw_text = _clean_text(_first(row, ("raw_text", "text", "line_text", "product", "product_name", "description")))
    raw_text = _clean_text(" ".join(part for part in (raw_text, token_text, cell_text, column_text) if part))
    numeric_tokens = NUMERIC_RE.findall(raw_text)
    product_like_tokens = [match.group(0) for match in PRODUCT_RE.finditer(raw_text)]
    role = str(_first(row, ("row_role", "role", "classification", "type")) or "unknown")
    issues = []
    role_l = role.lower()
    if row_id not in canonical_by_row and "item_rows_clean" not in source_path:
        issues.append("row_without_canonical_mapping")
    if numeric_tokens and not product_like_tokens:
        issues.append("numeric_row_without_product")
    if product_like_tokens and not numeric_tokens and _looks_item_role(role_l):
        issues.append("product_row_without_numeric_fields")
    if FOOTER_RE.search(raw_text) and _looks_item_role(role_l):
        issues.append("footer_keyword_inside_item_row")
    if TAX_RE.search(raw_text) and _looks_item_role(role_l):
        issues.append("tax_keyword_inside_item_row")
    return {
        "row_id": row_id,
        "table_id": table_id or row.get("table_id"),
        "role": role,
        "raw_text": raw_text,
        "y_min": _extract_geometry(row).get("y_min"),
        "y_max": _extract_geometry(row).get("y_max"),
        "cells": cells,
        "numeric_tokens": numeric_tokens,
        "product_like_tokens": product_like_tokens[:12],
        "footer_tax_keywords": _keyword_hits(raw_text),
        "assigned_canonical_row": canonical_by_row.get(row_id),
        "row_math_status": row_math.get(row_id),
        "issues": issues,
        "source_path": source_path,
    }


def _extract_columns(raw_result: dict, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    columns_by_key: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
    semantics = _collect_semantics(raw_result)

    for table_idx, table in enumerate(_as_list(raw_result.get("structured_tables"))):
        if not isinstance(table, dict):
            continue
        table_id = table.get("table_id")
        cells_by_col = defaultdict(list)
        for cell in _as_list(table.get("cells")):
            if isinstance(cell, dict):
                cells_by_col[cell.get("col_id")].append(cell)
        for col_idx, col in enumerate(_as_list(table.get("columns"))):
            if not isinstance(col, dict):
                continue
            col_id = col.get("col_id") or f"col_{col_idx}"
            columns_by_key[(table_id, col_id)] = _column_from_parts(
                table_id, col_id, col, cells_by_col.get(col_id, []), semantics, f"structured_tables[{table_idx}].columns[{col_idx}]"
            )

    topology_tables = _get_path(raw_result, ("metrics", "topology_debug", "main_tables"))
    for table_idx, table in enumerate(_as_list(topology_tables)):
        if not isinstance(table, dict):
            continue
        table_id = table.get("table_id")
        cells = _as_list(table.get("current_reconstructed_cells"))
        cells_by_col = defaultdict(list)
        for cell in cells:
            if isinstance(cell, dict):
                cells_by_col[cell.get("col_id")].append(cell)
        for col_idx, col in enumerate(_as_list(table.get("current_column_boundaries"))):
            if not isinstance(col, dict):
                continue
            col_id = col.get("col_id") or f"col_{col_idx}"
            columns_by_key.setdefault(
                (table_id, col_id),
                _column_from_parts(table_id, col_id, col, cells_by_col.get(col_id, []), semantics, f"metrics.topology_debug.main_tables[{table_idx}].columns[{col_idx}]"),
            )

    if not columns_by_key:
        inferred = defaultdict(list)
        for row in rows:
            for cell in row.get("cells") or []:
                inferred[cell.get("col_id")].append(cell)
        for col_id, cells in inferred.items():
            columns_by_key[(None, col_id)] = _column_from_parts(None, col_id, {}, cells, semantics, "inferred.cells")

    return list(columns_by_key.values())


def _column_from_parts(table_id, col_id, col, cells, semantics, source_path) -> Dict[str, Any]:
    text_values = [_clean_text(cell.get("text")) for cell in cells if isinstance(cell, dict)]
    numeric_count = sum(1 for text in text_values if NUMERIC_RE.search(text))
    text_count = sum(1 for text in text_values if PRODUCT_RE.search(text))
    contamination = [text for text in text_values if FOOTER_RE.search(text) or TAX_RE.search(text)]
    label = semantics.get((table_id, col_id)) or semantics.get((None, col_id)) or _first(col, ("semantic_label", "semantic", "type"))
    header_text = _first(col, ("header", "header_text", "text")) or _infer_header_text(text_values)
    issues = []
    label_l = str(label or "").lower()
    if contamination and label_l in {"amount", "rate", "quantity", "free_quantity", "taxable_value"}:
        issues.append("semantic_column_poisoning_candidate")
    if label_l == "amount" and any(TAX_RE.search(text) for text in text_values):
        issues.append("amount_column_contains_tax_keyword")
    if label_l in {"quantity", "free_quantity"} and any("+" in text for text in text_values):
        issues.append("qty_free_merged_column")
    if header_text and label and _header_conflicts(header_text, str(label)):
        issues.append("column_label_conflicts_with_header")
    geometry = _extract_geometry(col)
    return {
        "table_id": table_id,
        "column_id": str(col_id),
        "x_min": geometry.get("x_min"),
        "x_max": geometry.get("x_max"),
        "header_text": header_text,
        "semantic_label": label,
        "semantic_confidence": _safe_float(_first(col, ("confidence", "semantic_confidence"))),
        "numeric_cell_count": numeric_count,
        "text_cell_count": text_count,
        "footer_tax_keyword_contamination_count": len(contamination),
        "contamination_tokens": contamination[:10],
        "item_row_only_label": label,
        "all_row_label": label,
        "issues": issues,
        "source_path": source_path,
    }


def _extract_canonical_trace(canonical: dict, rows: List[Dict[str, Any]], tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    row_by_id = {str(row.get("row_id")): row for row in rows}
    trace = []
    for idx, item in enumerate(_as_list(canonical.get("item_rows"))):
        if not isinstance(item, dict):
            continue
        row_id = str(item.get("row_id") or idx)
        source_path = str(item.get("source_path") or "")
        source_row = row_by_id.get(row_id)
        missing = []
        for field in ("product", "qty", "rate", "amount"):
            if not _field_has_source(item.get(field), source_path, source_row, tokens):
                missing.append(f"{field}_missing_source")
        issues = list(missing)
        if source_path and not _known_source_path(source_path):
            issues.append("canonical_field_from_unknown_path")
        if _row_math_failed(row_id, source_row):
            issues.append("row_math_failed_with_source_present" if not missing else "row_math_failed_with_source_missing")
        trace.append({
            "row_id": row_id,
            "product": item.get("product"),
            "qty": item.get("qty"),
            "free_qty": item.get("free_qty"),
            "rate": item.get("rate"),
            "amount": item.get("amount"),
            "raw_text": item.get("raw_text"),
            "source_path": source_path,
            "matched_source_row": source_row.get("row_id") if source_row else None,
            "matched_source_cells": source_row.get("cells") if source_row else [],
            "matched_source_tokens": _tokens_for_text(tokens, item.get("raw_text") or item.get("product")),
            "fields_missing_source_evidence": missing,
            "issues": issues,
        })
    row_ids = {entry["row_id"] for entry in trace}
    for row in rows:
        if _looks_item_role(str(row.get("role", "")).lower()) and row.get("row_id") not in row_ids:
            row.setdefault("issues", []).append("canonical_row_without_source_row")
    return trace


def _build_summary(raw_result, tokens, rows, columns, canonical_trace, footer_leakage_candidates, semantic_poisoning_candidates, row_grouping_warnings):
    top_issues = Counter()
    for collection in (rows, columns, canonical_trace):
        for entry in collection:
            top_issues.update(entry.get("issues") or [])
    top_issues.update(candidate.get("issue") for candidate in footer_leakage_candidates if candidate.get("issue"))
    top_issues.update(candidate.get("issue") for candidate in semantic_poisoning_candidates if candidate.get("issue"))
    top_issues.update(warning.get("issue") for warning in row_grouping_warnings if warning.get("issue"))
    suspected = _suspected_failure_layer(raw_result, tokens, rows, columns, canonical_trace, top_issues)
    return {
        "ocr_token_count": len(tokens),
        "row_count": len(rows),
        "cell_count": sum(len(row.get("cells") or []) for row in rows),
        "canonical_item_count": len(canonical_trace),
        "tokens_with_row_assignment": sum(1 for token in tokens if token.get("assigned_row_id")),
        "tokens_with_column_assignment": sum(1 for token in tokens if token.get("assigned_column_id")),
        "tokens_with_semantic_label": sum(1 for token in tokens if token.get("semantic_label")),
        "canonical_fields_with_source": sum(4 - len(entry.get("fields_missing_source_evidence") or []) for entry in canonical_trace),
        "suspected_failure_layer": suspected,
        "top_issues": [issue for issue, _ in top_issues.most_common(10) if issue],
    }


def _suspected_failure_layer(raw_result, tokens, rows, columns, canonical_trace, issues: Counter) -> str:
    if not tokens:
        return "ocr_missing"
    if not rows:
        return "row_grouping_failure"
    if not any(row.get("cells") for row in rows):
        return "insufficient_debug_evidence"
    if not any(token.get("assigned_row_id") for token in tokens):
        return "token_cell_assignment_failure"
    if not columns:
        return "column_band_failure"
    if issues.get("footer_keyword_inside_item_row") or issues.get("tax_keyword_inside_item_row"):
        return "footer_leakage_failure"
    if issues.get("semantic_column_poisoning_candidate") or issues.get("column_label_conflicts_with_header"):
        return "semantic_classifier_failure"
    if issues.get("qty_missing_source") or issues.get("rate_missing_source") or issues.get("amount_missing_source"):
        return "canonical_adapter_failure"
    if raw_result.get("quality_gate") and not _get_path(raw_result, ("metrics", "financial_reconciliation")):
        return "validator_schema_failure"
    return "insufficient_debug_evidence"


def _target_product_trace(target_products, tokens, rows, canonical_trace):
    if not target_products:
        return []
    traces = []
    for target in target_products:
        terms = _target_terms(target)
        matching_tokens = [token for token in tokens if _matches_terms(token.get("text"), terms)]
        matching_rows = [row for row in rows if _matches_terms(row.get("raw_text"), terms)]
        row_ids = {row.get("row_id") for row in matching_rows}
        nearby_numeric = [
            token for token in tokens
            if token.get("assigned_row_id") in row_ids and NUMERIC_RE.search(str(token.get("text") or ""))
        ]
        matching_canonical = [entry for entry in canonical_trace if _matches_terms(entry.get("product") or entry.get("raw_text"), terms)]
        traces.append({
            "target": target,
            "terms": terms,
            "matching_tokens": matching_tokens,
            "matching_rows": matching_rows,
            "nearby_numeric_tokens": nearby_numeric,
            "matching_canonical_rows": matching_canonical,
            "expected_value_presence": {
                "2.500+.500": any("2.500+.500" in _compact(_trace_text(entry)) for entry in tokens + matching_rows),
                "71.34": any("71.34" in str(token.get("text") or token.get("raw_text") or "") for token in tokens + matching_rows),
                "196.19": any("196.19" in str(token.get("text") or token.get("raw_text") or "") for token in tokens + matching_rows),
            },
        })
    return traces


def _footer_leakage(rows):
    candidates = []
    for row in rows:
        text = row.get("raw_text") or ""
        if FOOTER_RE.search(text) and _looks_item_role(str(row.get("role", "")).lower()):
            candidates.append({"row_id": row.get("row_id"), "text": text, "issue": "footer_keyword_inside_item_row", "why": "footer keyword appears in item-like row"})
        if TAX_RE.search(text) and _looks_item_role(str(row.get("role", "")).lower()):
            candidates.append({"row_id": row.get("row_id"), "text": text, "issue": "tax_keyword_inside_item_row", "why": "tax keyword appears in item-like row"})
    return candidates


def _semantic_poisoning(columns):
    candidates = []
    for col in columns:
        if "semantic_column_poisoning_candidate" in (col.get("issues") or []):
            candidates.append({
                "column_id": col.get("column_id"),
                "table_id": col.get("table_id"),
                "label": col.get("semantic_label"),
                "contamination_tokens": col.get("contamination_tokens") or [],
                "affected_rows": [],
                "issue": "semantic_column_poisoning_candidate",
            })
    return candidates


def _row_grouping_warnings(rows):
    warnings = []
    sorted_rows = sorted(rows, key=lambda row: (row.get("y_min") is None, row.get("y_min") or 0))
    for idx, row in enumerate(sorted_rows):
        text = row.get("raw_text") or ""
        if PRODUCT_RE.search(text) and not NUMERIC_RE.search(text):
            warnings.append({"row_id": row.get("row_id"), "issue": "multi_line_product_split_candidate", "text": text})
        if NUMERIC_RE.search(text) and not PRODUCT_RE.search(text) and idx > 0:
            prev = sorted_rows[idx - 1]
            if PRODUCT_RE.search(prev.get("raw_text") or ""):
                warnings.append({
                    "row_id": row.get("row_id"),
                    "nearby_row_id": prev.get("row_id"),
                    "issue": "nearby_numeric_row_may_be_continuation",
                    "text": text,
                })
    return warnings


def _add_row_context_warnings(rows):
    warnings_by_id = defaultdict(list)
    for warning in _row_grouping_warnings(rows):
        warnings_by_id[warning.get("row_id")].append(warning.get("issue"))
    for row in rows:
        for issue in warnings_by_id.get(row.get("row_id"), []):
            if issue and issue not in row["issues"]:
                row["issues"].append(issue)


def _cell_index(raw_result):
    index = defaultdict(list)
    for table_idx, table in enumerate(_as_list(raw_result.get("structured_tables"))):
        if not isinstance(table, dict):
            continue
        semantics = _collect_semantics(raw_result)
        for cell_idx, cell in enumerate(_as_list(table.get("cells"))):
            if isinstance(cell, dict):
                copied = dict(cell)
                copied["cell_id"] = copied.get("cell_id") or f"{copied.get('row_id')}:{copied.get('col_id')}"
                copied["semantic_label"] = semantics.get((table.get("table_id"), copied.get("col_id"))) or semantics.get((None, copied.get("col_id")))
                copied["source_path"] = f"structured_tables[{table_idx}].cells[{cell_idx}]"
                index[str(copied.get("row_id"))].append(copied)
    topology_tables = _get_path(raw_result, ("metrics", "topology_debug", "main_tables"))
    for table_idx, table in enumerate(_as_list(topology_tables)):
        if not isinstance(table, dict):
            continue
        for cell_idx, cell in enumerate(_as_list(table.get("current_reconstructed_cells"))):
            if isinstance(cell, dict):
                copied = dict(cell)
                copied["cell_id"] = copied.get("cell_id") or f"{copied.get('row_id')}:{copied.get('col_id')}"
                copied["source_path"] = f"metrics.topology_debug.main_tables[{table_idx}].cells[{cell_idx}]"
                index[str(copied.get("row_id"))].append(copied)
    return index


def _collect_semantics(raw_result):
    semantics = {}
    final = _get_path(raw_result, ("metrics", "final_column_semantics"))
    if isinstance(final, dict):
        for table_id, cols in final.items():
            if isinstance(cols, dict):
                for col_id, label in cols.items():
                    semantics[(table_id, col_id)] = label
            else:
                semantics[(None, table_id)] = cols
    cache = _get_path(raw_result, ("metrics", "column_semantic_cache"))
    if isinstance(cache, dict):
        for table_id, cols in cache.items():
            if not isinstance(cols, dict):
                continue
            for col_id, data in cols.items():
                if isinstance(data, dict):
                    semantics[(table_id, col_id)] = data.get("type") or data.get("semantic_label")
    topology_tables = _get_path(raw_result, ("metrics", "topology_debug", "main_tables"))
    for table in _as_list(topology_tables):
        if isinstance(table, dict) and isinstance(table.get("current_semantic_labels"), dict):
            for col_id, label in table["current_semantic_labels"].items():
                semantics[(table.get("table_id"), col_id)] = label
    return semantics


def _row_math_status(raw_result):
    status = {}
    details = _get_path(raw_result, ("metrics", "financial_reconciliation", "main", "row_math_details"))
    for detail in _as_list(details):
        if isinstance(detail, dict):
            row_id = detail.get("row_id") or detail.get("visual_row_id")
            if row_id:
                status[str(row_id)] = detail.get("status") or ("failed" if detail.get("failed") else "unknown")
    return status


def _canonical_by_row(canonical):
    by_row = {}
    if not isinstance(canonical, dict):
        return by_row
    for item in _as_list(canonical.get("item_rows")):
        if isinstance(item, dict) and item.get("row_id") is not None:
            by_row[str(item.get("row_id"))] = item.get("product") or item.get("raw_text") or "canonical_item"
    return by_row


def _mark_canonical_appearances(tokens, canonical):
    if not isinstance(canonical, dict):
        return
    fields = []
    for item in _as_list(canonical.get("item_rows")):
        if isinstance(item, dict):
            for field in ("product", "qty", "free_qty", "rate", "amount"):
                value = item.get(field)
                if value not in (None, ""):
                    fields.append((field, str(value).lower()))
    for footer in _as_list(canonical.get("footer_fields")):
        if isinstance(footer, dict) and footer.get("value") not in (None, ""):
            fields.append((f"footer:{footer.get('label')}", str(footer.get("value")).lower()))
    for token in tokens:
        text = str(token.get("text") or "").lower()
        hits = [field for field, value in fields if value and (value in text or text in value)]
        token["appears_in_canonical_fields"] = hits


def _field_has_source(value, source_path, source_row, tokens):
    if value in (None, ""):
        return False
    value_text = str(value).strip().lower()
    if source_row and value_text and value_text in str(source_row.get("raw_text") or "").lower():
        return True
    if source_path and _known_source_path(source_path):
        return True
    return any(value_text in str(token.get("text") or "").lower() for token in tokens)


def _known_source_path(source_path):
    return source_path.startswith(("item_rows_clean", "item_rows", "structured_tables", "reconstructed_item_rows", "structured_rows", "line_items"))


def _row_math_failed(row_id, source_row):
    if source_row and str(source_row.get("row_math_status") or "").lower() in {"fail", "failed", "false"}:
        return True
    return False


def _tokens_for_text(tokens, text):
    if not text:
        return []
    text_l = str(text).lower()
    return [token for token in tokens if str(token.get("text") or "").lower() in text_l][:12]


def _extract_geometry(value):
    if not isinstance(value, dict):
        return _empty_geometry()
    geometry = value.get("geometry") or value.get("bbox") or value.get("box") or {}
    if isinstance(geometry, dict) and geometry:
        return {
            "x_min": _safe_float(_first(geometry, ("min_x", "x_min", "left", "x0"))),
            "x_max": _safe_float(_first(geometry, ("max_x", "x_max", "right", "x1"))),
            "y_min": _safe_float(_first(geometry, ("min_y", "y_min", "top", "y0"))),
            "y_max": _safe_float(_first(geometry, ("max_y", "y_max", "bottom", "y1"))),
            "center_x": _safe_float(_first(geometry, ("center_x", "x_center"))),
            "center_y": _safe_float(_first(geometry, ("center_y", "y_center"))),
        }
    polygon = value.get("polygon")
    if isinstance(polygon, list) and polygon:
        xs = [pt[0] for pt in polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
        ys = [pt[1] for pt in polygon if isinstance(pt, (list, tuple)) and len(pt) >= 2]
        if xs and ys:
            return {"x_min": min(xs), "x_max": max(xs), "y_min": min(ys), "y_max": max(ys), "center_x": (min(xs) + max(xs)) / 2, "center_y": (min(ys) + max(ys)) / 2}
    return {
        "x_min": _safe_float(_first(value, ("x_min", "min_x", "left", "x0"))),
        "x_max": _safe_float(_first(value, ("x_max", "max_x", "right", "x1"))),
        "y_min": _safe_float(_first(value, ("y_min", "min_y", "top", "y0"))),
        "y_max": _safe_float(_first(value, ("y_max", "max_y", "bottom", "y1"))),
        "center_x": _safe_float(_first(value, ("center_x", "x_center"))),
        "center_y": _safe_float(_first(value, ("center_y", "y_center"))),
    }


def _empty_geometry():
    return {"x_min": None, "x_max": None, "y_min": None, "y_max": None, "center_x": None, "center_y": None}


def _keyword_hits(text):
    hits = []
    if FOOTER_RE.search(text or ""):
        hits.append("footer")
    if TAX_RE.search(text or ""):
        hits.append("tax")
    return hits


def _infer_header_text(text_values):
    for text in text_values[:3]:
        if any(pattern.search(text or "") for pattern in HEADER_LABELS.values()):
            return text
    return ""


def _header_conflicts(header_text, label):
    label_l = label.lower()
    for expected, pattern in HEADER_LABELS.items():
        if pattern.search(header_text or ""):
            if expected == "qty" and label_l in {"quantity", "free_quantity"}:
                return False
            return expected != label_l
    return False


def _invoice_id(raw_result, canonical):
    metadata = raw_result.get("metadata") if isinstance(raw_result.get("metadata"), dict) else {}
    return str(canonical.get("invoice_id") or metadata.get("invoice_id") or raw_result.get("invoice_id") or "unknown")


def _canonical_dict(canonical_invoice):
    if canonical_invoice is None:
        return None
    if isinstance(canonical_invoice, dict):
        return canonical_invoice
    if hasattr(canonical_invoice, "to_dict"):
        return canonical_invoice.to_dict()
    return None


def _target_terms(target):
    target_u = str(target).upper()
    if "RANIDOM" in target_u:
        return ["RANIDOM", "MPS", "SUSP"]
    return [part for part in re.split(r"\W+", target_u) if part]


def _matches_terms(text, terms):
    text_u = str(text or "").upper()
    return any(term in text_u for term in terms)


def _compact(value):
    return re.sub(r"\s+", "", str(value or ""))


def _trace_text(entry):
    if not isinstance(entry, dict):
        return ""
    return entry.get("text") or entry.get("raw_text") or entry.get("line_text") or ""


def _looks_item_role(role):
    return any(part in role for part in ("item", "medicine", "table")) and not any(part in role for part in ("footer", "tax", "header"))


def _as_list(value):
    return value if isinstance(value, list) else []


def _get_path(data, path):
    current = data
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _first(mapping, keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()
