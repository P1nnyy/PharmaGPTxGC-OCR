import re
from typing import Any, Dict, List, Optional, Set, Tuple

from core.logger import logger
from models.layout_models import TableCell, TableRegion


class ColumnSemantics:
    PRODUCT = "product"
    BATCH = "batch"
    EXPIRY = "expiry"
    HSN = "hsn"
    QUANTITY = "quantity"
    FREE_QUANTITY = "free_quantity"
    MRP = "mrp"
    RATE = "rate"
    DISCOUNT = "discount"
    TAXABLE_VALUE = "taxable_value"
    GST = "gst"
    AMOUNT = "amount"
    UNKNOWN = "unknown"


NUMERIC_SEMANTICS = {
    ColumnSemantics.QUANTITY,
    ColumnSemantics.FREE_QUANTITY,
    ColumnSemantics.MRP,
    ColumnSemantics.RATE,
    ColumnSemantics.DISCOUNT,
    ColumnSemantics.TAXABLE_VALUE,
    ColumnSemantics.GST,
    ColumnSemantics.AMOUNT,
}


class SemanticColumnClassifier:
    """
    Geometry-aware semantic classifier for reconstructed table columns.

    The classifier only infers item-table column meanings from rows marked
    item_row. Footer/tax/header/metadata rows are left available downstream for
    totals extraction but do not vote on item column semantics.
    """

    GST_VALUES = {0.0, 2.5, 5.0, 6.0, 9.0, 12.0, 18.0, 28.0}
    FOOTER_SIGNAL_RE = re.compile(
        r"\b(SUB\s*TOTAL|GRAND\s*TOTAL|ROUND\s*OFF|ROUNDOFF|DISCOUNT|LESS|"
        r"CGST|SGST|IGST|GST\s*SUMMARY|AMOUNT\s+IN\s+WORDS|NET\s*(?:AMT|AMOUNT|PAYABLE))\b",
        re.IGNORECASE,
    )
    HEADER_LABEL_PATTERNS = {
        ColumnSemantics.PRODUCT: re.compile(r"\b(?:PRODUCT|ITEM|DESCRIPTION|PARTICULARS?)\b", re.IGNORECASE),
        ColumnSemantics.BATCH: re.compile(r"\bBATCH\b", re.IGNORECASE),
        ColumnSemantics.EXPIRY: re.compile(r"\bEXP(?:IRY)?\b", re.IGNORECASE),
        ColumnSemantics.HSN: re.compile(r"\bHSN\b", re.IGNORECASE),
        ColumnSemantics.QUANTITY: re.compile(r"\b(?:QTY|QUANTITY)\b", re.IGNORECASE),
        ColumnSemantics.FREE_QUANTITY: re.compile(r"\bFREE\b", re.IGNORECASE),
        ColumnSemantics.MRP: re.compile(r"\bMRP\b", re.IGNORECASE),
        ColumnSemantics.RATE: re.compile(r"\bRATE\b", re.IGNORECASE),
        ColumnSemantics.DISCOUNT: re.compile(r"\b(?:DIS|DISC|DISCOUNT|TD)\b", re.IGNORECASE),
        ColumnSemantics.GST: re.compile(r"\b(?:GST|CGST|SGST|IGST)\b", re.IGNORECASE),
        ColumnSemantics.AMOUNT: re.compile(r"\b(?:AMOUNT|AMT|VALUE)\b", re.IGNORECASE),
    }

    def _compact(self, text: str) -> str:
        return re.sub(r"\s+", "", (text or "").strip().upper())

    def _numeric_value(self, text: str) -> Optional[float]:
        cleaned = re.sub(r"[₹$,%\s,]", "", (text or "").upper())
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _has_compound_qty_pattern(self, compact: str) -> bool:
        return bool(re.search(r"\d+(?:\.\d+)?[+*xX]\.?\d+", compact))

    def _has_pharma_qty_pattern(self, raw: str, compact: str) -> bool:
        if self._has_compound_qty_pattern(compact):
            return True
        if re.search(r"\b\d{1,2}\.\b", raw):
            return True
        return bool(re.fullmatch(r"\d{1,2}", compact))

    def _table_x_bounds(self, region: TableRegion) -> Tuple[float, float]:
        if region.geometry:
            return region.geometry.min_x, region.geometry.max_x

        xs: List[float] = []
        for col in region.columns:
            if col.geometry:
                xs.extend([col.geometry.min_x, col.geometry.max_x])
        for cell in region.cells:
            if cell.geometry:
                xs.extend([cell.geometry.min_x, cell.geometry.max_x])
        if not xs:
            return 0.0, 1.0
        return min(xs), max(xs)

    def _x_ratio(self, region: TableRegion, col_id: str, fallback_center_x: Optional[float] = None) -> float:
        table_min_x, table_max_x = self._table_x_bounds(region)
        span = max(1.0, table_max_x - table_min_x)

        center_x = fallback_center_x
        col = next((c for c in region.columns if c.col_id == col_id), None)
        if col and col.geometry:
            center_x = col.geometry.center_x
        if center_x is None:
            center_x = table_min_x + (span / 2.0)
        return max(0.0, min(1.0, (center_x - table_min_x) / span))

    def _text_features(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        compact = self._compact(raw)
        content_chars = [c for c in compact if c.isalnum() or c in "./-%"]
        alpha = sum(1 for c in content_chars if c.isalpha())
        digit = sum(1 for c in content_chars if c.isdigit())
        decimal = 1 if re.search(r"\d+\.\d+", compact) else 0
        denom = max(1, len(content_chars))
        numeric_value = self._numeric_value(compact)

        is_expiry = bool(re.fullmatch(r"\d{1,2}[/-]\d{2,4}", compact))
        is_hsn = bool(re.fullmatch(r"\d{6,8}", compact))
        is_batch = (
            bool(re.fullmatch(r"[A-Z0-9-]{5,20}", compact))
            and bool(re.search(r"[A-Z]", compact))
            and bool(re.search(r"\d", compact))
            and not bool(re.search(r"\s", raw))
            and not is_expiry
            and not is_hsn
        )
        is_money = bool(re.fullmatch(r"[₹$]?\d[\d,]*\.\d{1,3}%?", compact))
        is_integer = bool(re.fullmatch(r"\d+", compact))
        has_compound_qty = self._has_compound_qty_pattern(compact)
        is_qty = (
            self._has_pharma_qty_pattern(raw, compact)
            and not is_hsn
            and not is_expiry
        )
        is_gst = (
            "GST" in compact
            or "CGST" in compact
            or "SGST" in compact
            or "IGST" in compact
            or (numeric_value in self.GST_VALUES if numeric_value is not None else False)
        )
        has_discount_token = bool(re.search(r"(DISC|DISCOUNT|LESS)", compact))

        return {
            "alpha_chars": alpha,
            "digit_chars": digit,
            "decimal_chars": decimal,
            "char_count": denom,
            "alpha_ratio": alpha / denom,
            "digit_ratio": digit / denom,
            "is_decimal": bool(decimal),
            "is_expiry": is_expiry,
            "is_hsn": is_hsn,
            "is_batch": is_batch,
            "is_money": is_money,
            "is_integer": is_integer,
            "is_qty": is_qty,
            "is_compound_qty": has_compound_qty,
            "is_gst": is_gst,
            "is_discount": has_discount_token,
            "is_long_alpha_text": len(raw) >= 10 and alpha >= 4,
            "numeric_value": numeric_value,
        }

    def _column_profile(self, region: TableRegion, col_id: str, active_cells: List[TableCell]) -> Dict[str, Any]:
        features = [self._text_features(c.text) for c in active_cells]
        sample_size = len(features)
        centers = [c.geometry.center_x for c in active_cells if c.geometry]
        avg_center_x = sum(centers) / len(centers) if centers else None
        right_side_score = self._x_ratio(region, col_id, avg_center_x)

        total_chars = max(1, sum(f["char_count"] for f in features))
        alpha_density = sum(f["alpha_chars"] for f in features) / total_chars
        digit_density = sum(f["digit_chars"] for f in features) / total_chars
        decimal_density = sum(f["decimal_chars"] for f in features) / max(1, sample_size)

        numeric_values = [
            f["numeric_value"]
            for f in features
            if f["numeric_value"] is not None
        ]
        gst_value_count = sum(1 for v in numeric_values if v in self.GST_VALUES)

        return {
            "sample_size": sample_size,
            "unique_row_support": len({c.row_id for c in active_cells}),
            "alpha_density": alpha_density,
            "digit_density": digit_density,
            "decimal_density": decimal_density,
            "expiry_pattern_count": sum(1 for f in features if f["is_expiry"]),
            "batch_pattern_count": sum(1 for f in features if f["is_batch"]),
            "hsn_pattern_count": sum(1 for f in features if f["is_hsn"]),
            "gst_pattern_count": sum(1 for f in features if f["is_gst"]),
            "money_pattern_count": sum(1 for f in features if f["is_money"]),
            "qty_pattern_count": sum(1 for f in features if f["is_qty"]),
            "compound_qty_pattern_count": sum(1 for f in features if f["is_compound_qty"]),
            "integer_pattern_count": sum(1 for f in features if f["is_integer"]),
            "discount_pattern_count": sum(1 for f in features if f["is_discount"]),
            "long_alpha_text_count": sum(1 for f in features if f["is_long_alpha_text"]),
            "gst_small_value_count": gst_value_count,
            "numeric_value_min": min(numeric_values) if numeric_values else None,
            "numeric_value_max": max(numeric_values) if numeric_values else None,
            "avg_center_x": avg_center_x,
            "right_side_score": right_side_score,
        }

    def _column_context(self, region: TableRegion, col_id: str, row_roles: Dict[str, str]) -> Dict[str, Any]:
        header_votes: Dict[str, int] = {}
        footer_signal_count = 0
        non_item_numeric_outlier_count = 0

        for cell in region.cells:
            if cell.col_id != col_id or not (cell.text or "").strip():
                continue
            role = row_roles.get(cell.row_id, "unknown_row")
            text = cell.text or ""
            if role == "header_row":
                for semantic_type, pattern in self.HEADER_LABEL_PATTERNS.items():
                    if pattern.search(text):
                        header_votes[semantic_type] = header_votes.get(semantic_type, 0) + 1
            elif role in {"footer_summary_row", "tax_summary_row", "metadata_row"}:
                if self.FOOTER_SIGNAL_RE.search(text):
                    footer_signal_count += 1
                if self._text_features(text)["is_money"]:
                    non_item_numeric_outlier_count += 1

        return {
            "header_votes": header_votes,
            "footer_signal_count": footer_signal_count,
            "non_item_numeric_outlier_count": non_item_numeric_outlier_count,
        }

    def _base_scores(self, profile: Dict[str, Any]) -> Dict[str, float]:
        sample_size = max(1, profile["sample_size"])
        expiry_ratio = profile["expiry_pattern_count"] / sample_size
        batch_ratio = profile["batch_pattern_count"] / sample_size
        hsn_ratio = profile["hsn_pattern_count"] / sample_size
        gst_ratio = profile["gst_pattern_count"] / sample_size
        money_ratio = profile["money_pattern_count"] / sample_size
        qty_ratio = profile["qty_pattern_count"] / sample_size
        right_side = profile["right_side_score"]

        scores = {
            ColumnSemantics.PRODUCT: 0.0,
            ColumnSemantics.BATCH: batch_ratio * 4.0,
            ColumnSemantics.EXPIRY: expiry_ratio * 5.0,
            ColumnSemantics.HSN: hsn_ratio * 5.0,
            ColumnSemantics.QUANTITY: qty_ratio * 3.0,
            ColumnSemantics.FREE_QUANTITY: 0.0,
            ColumnSemantics.MRP: 0.0,
            ColumnSemantics.RATE: 0.0,
            ColumnSemantics.DISCOUNT: profile["discount_pattern_count"] * 2.0,
            ColumnSemantics.TAXABLE_VALUE: 0.0,
            ColumnSemantics.GST: gst_ratio * 3.5,
            ColumnSemantics.AMOUNT: 0.0,
            ColumnSemantics.UNKNOWN: 0.0,
        }

        if profile["alpha_density"] >= 0.35 and right_side <= 0.55:
            scores[ColumnSemantics.PRODUCT] += 2.0 + (profile["alpha_density"] * 3.0)
        if profile["long_alpha_text_count"] > 0 and right_side <= 0.65:
            scores[ColumnSemantics.PRODUCT] += 1.5

        if money_ratio >= 0.45 and profile["alpha_density"] <= 0.18:
            money_score = money_ratio * 2.0
            scores[ColumnSemantics.MRP] += money_score * max(0.2, 1.0 - right_side)
            scores[ColumnSemantics.RATE] += money_score
            scores[ColumnSemantics.TAXABLE_VALUE] += money_score * right_side
            scores[ColumnSemantics.AMOUNT] += money_score * (1.0 + right_side)

        for semantic_type, count in profile.get("header_votes", {}).items():
            if semantic_type in scores:
                scores[semantic_type] += min(3.0, count * 2.0)

        if profile.get("footer_signal_count", 0):
            penalty = min(1.5, profile["footer_signal_count"] * 0.5)
            for semantic_type in (ColumnSemantics.GST, ColumnSemantics.TAXABLE_VALUE, ColumnSemantics.AMOUNT):
                scores[semantic_type] = max(0.0, scores[semantic_type] - penalty)

        return scores

    def _strong_non_amount_signal(self, profile: Dict[str, Any]) -> bool:
        sample_size = max(1, profile["sample_size"])
        return (
            profile["alpha_density"] >= 0.28
            or profile["expiry_pattern_count"] / sample_size >= 0.35
            or profile["batch_pattern_count"] / sample_size >= 0.35
            or profile["hsn_pattern_count"] / sample_size >= 0.35
            or profile["gst_small_value_count"] / sample_size >= 0.55
        )

    def _strict_amount_candidate(self, profile: Dict[str, Any]) -> Tuple[bool, List[str]]:
        sample_size = max(1, profile["sample_size"])
        reasons: List[str] = []
        if profile["money_pattern_count"] / sample_size < 0.45:
            reasons.append("insufficient_money_like_cells")
        if profile["alpha_density"] > 0.18:
            reasons.append("alpha_density_too_high")
        if profile["right_side_score"] < 0.55:
            reasons.append("not_right_side_column")
        if profile["expiry_pattern_count"] > 0:
            reasons.append("expiry_signal_present")
        if profile["batch_pattern_count"] > 0:
            reasons.append("batch_signal_present")
        if profile["hsn_pattern_count"] > 0:
            reasons.append("hsn_signal_present")
        if profile["gst_small_value_count"] / sample_size >= 0.55:
            reasons.append("gst_small_value_pattern")
        return not reasons, reasons

    def _quantity_candidate_reason(self, profile: Dict[str, Any]) -> Tuple[bool, str]:
        sample_size = max(1, profile["sample_size"])
        qty_ratio = profile["qty_pattern_count"] / sample_size
        compound_ratio = profile["compound_qty_pattern_count"] / sample_size
        money_ratio = profile["money_pattern_count"] / sample_size
        right_side = profile["right_side_score"]

        if right_side >= 0.55:
            return False, "right_of_expected_quantity_zone"
        if money_ratio >= 0.45 and compound_ratio < 0.25:
            return False, "money_like_column"
        if profile["alpha_density"] > 0.5 and compound_ratio < 0.25:
            return False, "alpha_density_too_high"
        if self._strong_non_amount_signal(profile) and compound_ratio < 0.25:
            return False, "strong_non_quantity_signal"
        if compound_ratio >= 0.25:
            return True, "compound_quantity_pattern"
        if qty_ratio >= 0.45 and profile["alpha_density"] <= 0.25 and money_ratio < 0.35:
            return True, "plain_quantity_pattern"
        return False, "insufficient_quantity_pattern"

    def _ratio(self, profile: Dict[str, Any], key: str) -> float:
        return profile.get(key, 0) / max(1, profile.get("sample_size", 0))

    def _round_metrics(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        rounded: Dict[str, Any] = {}
        for key, value in metrics.items():
            if isinstance(value, float):
                rounded[key] = round(value, 3)
            elif isinstance(value, dict):
                rounded[key] = self._round_metrics(value)
            else:
                rounded[key] = value
        return rounded

    def analyze_table_columns(self, region: TableRegion) -> Dict[str, Dict[str, Any]]:
        """
        Score item-row cells per reconstructed column and return semantic labels.
        """
        analysis_results: Dict[str, Dict[str, Any]] = {}
        row_roles = {r.row_id: getattr(r, "row_role", "unknown_row") for r in region.rows}
        excluded_roles = {"header_row", "footer_summary_row", "tax_summary_row", "metadata_row"}
        item_row_ids: Set[str] = {
            row_id
            for row_id, role in row_roles.items()
            if role == "item_row" and role not in excluded_roles
        }
        columns_inferred_from_item_rows_only = bool(item_row_ids)

        semantic_column_scores_by_col: Dict[str, Any] = {}
        final_column_semantics: Dict[str, str] = {}
        amount_column_candidates: List[Dict[str, Any]] = []
        rejected_amount_candidates: List[Dict[str, Any]] = []
        product_column_candidates: List[str] = []
        expiry_column_candidates: List[str] = []
        batch_column_candidates: List[str] = []
        hsn_column_candidates: List[str] = []
        gst_column_candidates: List[str] = []
        quantity_column_candidates: List[Dict[str, Any]] = []
        rejected_quantity_candidates: List[Dict[str, Any]] = []

        profiles: Dict[str, Dict[str, Any]] = {}
        scores_by_col: Dict[str, Dict[str, float]] = {}
        hard_semantics: Dict[str, str] = {}
        money_candidates: List[str] = []
        quantity_candidates: List[str] = []

        for col in region.columns:
            col_id = col.col_id
            active_cells = [
                c for c in region.cells
                if c.col_id == col_id
                and c.row_id in item_row_ids
                and (c.text or "").strip()
            ]
            if not active_cells:
                analysis_results[col_id] = {
                    "type": ColumnSemantics.UNKNOWN,
                    "confidence": 0.0,
                    "metrics": {
                        "sample_size": 0,
                        "unique_row_support": 0,
                        "inferred_from_item_rows_only": columns_inferred_from_item_rows_only,
                    },
                }
                semantic_column_scores_by_col[col_id] = analysis_results[col_id]["metrics"]
                continue

            profile = self._column_profile(region, col_id, active_cells)
            profile.update(self._column_context(region, col_id, row_roles))
            scores = self._base_scores(profile)
            profiles[col_id] = profile
            scores_by_col[col_id] = scores
            sample_size = max(1, profile["sample_size"])
            required_support = 2 if len(item_row_ids) >= 2 else 1
            sufficient_row_support = profile["unique_row_support"] >= required_support

            expiry_ratio = self._ratio(profile, "expiry_pattern_count")
            hsn_ratio = self._ratio(profile, "hsn_pattern_count")
            batch_ratio = self._ratio(profile, "batch_pattern_count")
            gst_ratio = self._ratio(profile, "gst_pattern_count")
            money_ratio = self._ratio(profile, "money_pattern_count")
            qty_ratio = self._ratio(profile, "qty_pattern_count")
            compound_qty_ratio = self._ratio(profile, "compound_qty_pattern_count")
            gst_small_ratio = self._ratio(profile, "gst_small_value_count")
            quantity_eligible, quantity_reason = self._quantity_candidate_reason(profile)
            if quantity_eligible and sufficient_row_support:
                quantity_column_candidates.append({
                    "col_id": col_id,
                    "reason": quantity_reason,
                    "right_side_score": round(profile["right_side_score"], 3),
                    "qty_pattern_count": profile["qty_pattern_count"],
                    "compound_qty_pattern_count": profile["compound_qty_pattern_count"],
                    "sample_size": sample_size,
                })
            elif profile["qty_pattern_count"] > 0 or profile["compound_qty_pattern_count"] > 0:
                rejected_quantity_candidates.append({
                    "col_id": col_id,
                    "reason": quantity_reason,
                    "right_side_score": round(profile["right_side_score"], 3),
                    "qty_pattern_count": profile["qty_pattern_count"],
                    "compound_qty_pattern_count": profile["compound_qty_pattern_count"],
                    "money_pattern_count": profile["money_pattern_count"],
                    "alpha_density": round(profile["alpha_density"], 3),
                })

            amount_eligible, amount_reasons = self._strict_amount_candidate(profile)
            if amount_eligible and not sufficient_row_support:
                amount_eligible = False
                amount_reasons = [*amount_reasons, "insufficient_row_support_for_semantics"]
            if amount_eligible:
                amount_column_candidates.append({
                    "col_id": col_id,
                    "right_side_score": round(profile["right_side_score"], 3),
                    "money_pattern_count": profile["money_pattern_count"],
                    "sample_size": sample_size,
                })
                money_candidates.append(col_id)
            elif profile["money_pattern_count"] > 0 or profile["digit_density"] >= 0.6:
                rejected_amount_candidates.append({
                    "col_id": col_id,
                    "reason": ",".join(amount_reasons) or "not_selected_as_amount",
                    "right_side_score": round(profile["right_side_score"], 3),
                    "alpha_density": round(profile["alpha_density"], 3),
                    "digit_density": round(profile["digit_density"], 3),
                    "decimal_density": round(profile["decimal_density"], 3),
                })

            money_like_candidate = (
                money_ratio >= 0.45
                and profile["alpha_density"] <= 0.18
                and expiry_ratio < 0.25
                and batch_ratio < 0.25
                and hsn_ratio < 0.25
                and gst_small_ratio < 0.55
            )
            if money_like_candidate and sufficient_row_support and col_id not in money_candidates:
                money_candidates.append(col_id)

            if profile["alpha_density"] >= 0.35 and profile["right_side_score"] <= 0.6:
                product_column_candidates.append(col_id)
            if expiry_ratio >= 0.25 and sufficient_row_support:
                expiry_column_candidates.append(col_id)
            if batch_ratio >= 0.25 and sufficient_row_support:
                batch_column_candidates.append(col_id)
            if hsn_ratio >= 0.25 and sufficient_row_support:
                hsn_column_candidates.append(col_id)
            if sufficient_row_support and (gst_ratio >= 0.25 or gst_small_ratio >= 0.55):
                gst_column_candidates.append(col_id)

            if sufficient_row_support and expiry_ratio >= 0.35:
                hard_semantics[col_id] = ColumnSemantics.EXPIRY
            elif sufficient_row_support and hsn_ratio >= 0.35:
                hard_semantics[col_id] = ColumnSemantics.HSN
            elif sufficient_row_support and batch_ratio >= 0.35 and profile["alpha_density"] >= 0.12:
                hard_semantics[col_id] = ColumnSemantics.BATCH
            elif (
                sufficient_row_support
                and
                (gst_ratio >= 0.45 or gst_small_ratio >= 0.55)
                and profile["right_side_score"] >= 0.65
                and money_ratio <= 0.7
            ):
                hard_semantics[col_id] = ColumnSemantics.GST
            elif profile["alpha_density"] >= 0.35 and profile["right_side_score"] <= 0.55:
                hard_semantics[col_id] = ColumnSemantics.PRODUCT
            elif (
                sufficient_row_support
                and (
                    quantity_eligible
                    or (
                        qty_ratio >= 0.45
                        and profile["alpha_density"] <= 0.2
                        and money_ratio < 0.35
                        and not self._strong_non_amount_signal(profile)
                    )
                )
            ):
                quantity_candidates.append(col_id)
                if compound_qty_ratio >= 0.25:
                    scores[ColumnSemantics.QUANTITY] += compound_qty_ratio * 3.0

            analysis_results[col_id] = {
                "type": ColumnSemantics.UNKNOWN,
                "confidence": 0.0,
                "metrics": {
                    **self._round_metrics(profile),
                    "weighted_votes": {k: round(v, 3) for k, v in scores.items()},
                    "amount_eligible": amount_eligible,
                    "required_row_support": required_support,
                    "sufficient_row_support": sufficient_row_support,
                    "inferred_from_item_rows_only": columns_inferred_from_item_rows_only,
                },
            }
            semantic_column_scores_by_col[col_id] = analysis_results[col_id]["metrics"]

        quantity_candidates = sorted(
            [cid for cid in quantity_candidates if cid not in hard_semantics],
            key=lambda cid: profiles[cid]["right_side_score"],
        )
        if quantity_candidates:
            hard_semantics[quantity_candidates[0]] = ColumnSemantics.QUANTITY
            if len(quantity_candidates) > 1:
                hard_semantics[quantity_candidates[1]] = ColumnSemantics.FREE_QUANTITY

        money_candidates = sorted(
            [
                cid for cid in money_candidates
                if cid not in hard_semantics
                and not self._strong_non_amount_signal(profiles[cid])
            ],
            key=lambda cid: profiles[cid]["right_side_score"],
        )
        money_assignment: Dict[str, str] = {}
        if money_candidates:
            money_assignment[money_candidates[-1]] = ColumnSemantics.AMOUNT
            left_money = money_candidates[:-1]
            for idx, cid in enumerate(left_money):
                if profiles[cid]["discount_pattern_count"] > 0:
                    money_assignment[cid] = ColumnSemantics.DISCOUNT
                    continue
                if len(left_money) == 1:
                    money_assignment[cid] = ColumnSemantics.RATE
                elif idx == 0:
                    money_assignment[cid] = ColumnSemantics.MRP
                elif idx == 1:
                    money_assignment[cid] = ColumnSemantics.RATE
                else:
                    money_assignment[cid] = ColumnSemantics.TAXABLE_VALUE

        for col_id, data in analysis_results.items():
            if col_id.startswith("_") or col_id not in profiles:
                continue

            profile = profiles[col_id]
            scores = scores_by_col.get(col_id, {})
            if col_id in hard_semantics:
                best_type = hard_semantics[col_id]
            elif col_id in money_assignment:
                best_type = money_assignment[col_id]
            else:
                best_type, best_score = max(scores.items(), key=lambda item: item[1])
                if best_score <= 0.0:
                    best_type = ColumnSemantics.UNKNOWN
                if best_type == ColumnSemantics.AMOUNT and self._strong_non_amount_signal(profile):
                    rejected_amount_candidates.append({
                        "col_id": col_id,
                        "reason": "amount_vote_blocked_by_non_amount_signal",
                    })
                    best_type = ColumnSemantics.UNKNOWN

            best_score = scores.get(best_type, 0.0)
            sample_size = max(1, profile["sample_size"])
            if col_id in hard_semantics:
                best_score = max(best_score, 1.0)
            if col_id in money_assignment:
                best_score = max(best_score, profile["money_pattern_count"] / sample_size)

            sorted_scores = sorted(scores.values(), reverse=True)
            runner_up = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
            confidence = (best_score - runner_up) / max(1.0, sum(scores.values()))
            if col_id in hard_semantics or col_id in money_assignment:
                confidence = max(confidence, min(0.85, best_score))

            data["type"] = best_type
            data["confidence"] = round(max(0.0, min(0.95, confidence)), 3)
            final_column_semantics[col_id] = best_type

        analysis_results["_inference_summary"] = {
            "columns_inferred_from_item_rows_only": columns_inferred_from_item_rows_only,
            "item_rows_used": len(item_row_ids),
            "semantic_column_scores_by_col": semantic_column_scores_by_col,
            "final_column_semantics": final_column_semantics,
            "amount_column_candidates": amount_column_candidates,
            "rejected_amount_candidates": rejected_amount_candidates,
            "product_column_candidates": product_column_candidates,
            "expiry_column_candidates": expiry_column_candidates,
            "batch_column_candidates": batch_column_candidates,
            "hsn_column_candidates": hsn_column_candidates,
            "gst_column_candidates": gst_column_candidates,
            "quantity_column_candidates": quantity_column_candidates,
            "rejected_quantity_candidates": rejected_quantity_candidates,
        }
        return analysis_results

    def enrich_region_metadata(self, region: TableRegion) -> Dict[str, Any]:
        """
        Annotates semantic outliers without deleting OCR text.
        """
        results = self.analyze_table_columns(region)
        numeric_whitelist = r"^[ \d\+\*xX\.,₹$RS%\s\(\)-]+$"

        outliers = 0
        hard_deleted = 0
        for col_id, data in results.items():
            if col_id.startswith("_"):
                continue
            col_type = data["type"]
            if col_type not in NUMERIC_SEMANTICS:
                continue
            for cell in [c for c in region.cells if c.col_id == col_id]:
                if not (cell.text or "").strip():
                    continue
                if re.match(numeric_whitelist, cell.text.strip(), re.IGNORECASE):
                    continue
                if cell.original_text is None:
                    cell.original_text = cell.text
                cell.semantic_outlier = True
                cell.semantic_outlier_reason = "expected_numeric_column_but_text_found"
                outliers += 1

        if outliers > 0:
            logger.warning(
                f"[SEMANTIC QUARANTINE] Marked {outliers} non-conforming cells as semantic outliers."
            )
        results["_rejection_summary"] = {
            "semantic_rejection_count": outliers,
            "semantic_outlier_count": outliers,
            "hard_deleted_cells_count": hard_deleted,
            "quarantined_cell_count": outliers,
        }

        type_counts: Dict[str, int] = {}
        for col_id, data in results.items():
            if col_id.startswith("_"):
                continue
            col_type = data["type"]
            type_counts[col_type] = type_counts.get(col_type, 0) + 1

        logger.info(f"[COLUMN SEMANTICS] Final Semantic Breakdown: {type_counts}")
        return results
