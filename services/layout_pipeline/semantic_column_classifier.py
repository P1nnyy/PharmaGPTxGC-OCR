import re
from typing import List, Dict, Any, Tuple
from core.logger import logger
from models.layout_models import TableRegion, TableCell

class ColumnSemantics:
    AMOUNT = "amount"
    RATE = "rate"
    DISCOUNT = "discount"
    QUANTITY = "quantity"
    TAX = "tax"
    TEXT = "text"
    UNKNOWN = "unknown"

class SemanticColumnClassifier:
    """
    Post-Analysis Engine that consumes mapped cell contents to deduce the semantic purpose 
    of each structural column. Enables advanced telemetry and dynamic alignment reinforcement.
    """
    
    def __init__(self):
        pass

    def _cell_votes(self, text: str) -> Dict[str, float]:
        text_up = text.upper()
        votes = {
            ColumnSemantics.AMOUNT: 0.0,
            ColumnSemantics.RATE: 0.0,
            ColumnSemantics.DISCOUNT: 0.0,
            ColumnSemantics.QUANTITY: 0.0,
            ColumnSemantics.TAX: 0.0,
            ColumnSemantics.TEXT: 0.0,
        }

        if not text_up.strip():
            return votes

        has_digit = bool(re.search(r"\d", text_up))
        has_decimal = bool(re.search(r"\d+\.\d+", text_up))

        if any(kw in text_up for kw in ["DIS", "DISC", "TD%", "CD%"]):
            votes[ColumnSemantics.DISCOUNT] += 1.0
        if any(kw in text_up for kw in ["RATE", "UNIT PRICE", "MRP"]):
            votes[ColumnSemantics.RATE] += 1.0
        if any(kw in text_up for kw in ["GST", "CGST", "SGST", "IGST", "TAX"]):
            votes[ColumnSemantics.TAX] += 0.5

        if has_digit:
            if re.search(r"\d+\s*[\+\*xX]\s*\d+", text_up):
                votes[ColumnSemantics.QUANTITY] += 1.2
            elif has_decimal:
                votes[ColumnSemantics.AMOUNT] += 1.0
            else:
                votes[ColumnSemantics.QUANTITY] += 0.8
        else:
            votes[ColumnSemantics.TEXT] += 1.0

        return votes
        
    def analyze_table_columns(self, region: TableRegion) -> Dict[str, Dict[str, Any]]:
        """
        Scans all cell text inside each mapped ColumnRegion and scores their distribution profiles.
        Returns map of {col_id: {type, confidence, audit_metrics}}
        """
        analysis_results = {}
        
        row_roles = {r.row_id: getattr(r, "row_role", "unknown_row") for r in region.rows}
        item_row_ids = {row_id for row_id, role in row_roles.items() if role == "item_row"}
        columns_inferred_from_item_rows_only = bool(item_row_ids)
        preliminary_amount_cols = []

        for col in region.columns:
            c_id = col.col_id
            active_cells = [
                c for c in region.cells
                if c.col_id == c_id
                and c.row_id in item_row_ids
                and (c.text or "").strip()
            ]

            if not active_cells:
                analysis_results[c_id] = {
                    "type": ColumnSemantics.UNKNOWN,
                    "confidence": 0.0,
                    "metrics": {
                        "sample_size": 0,
                        "inferred_from_item_rows_only": columns_inferred_from_item_rows_only
                    }
                }
                continue

            total_count = len(active_cells)
            vote_totals = {
                ColumnSemantics.AMOUNT: 0.0,
                ColumnSemantics.RATE: 0.0,
                ColumnSemantics.DISCOUNT: 0.0,
                ColumnSemantics.QUANTITY: 0.0,
                ColumnSemantics.TAX: 0.0,
                ColumnSemantics.TEXT: 0.0,
            }
            numeric_count = decimal_count = tax_keywords_count = 0

            for c in active_cells:
                text = c.text.upper()
                if re.search(r'\d', text):
                    numeric_count += 1
                if '.' in text:
                    decimal_count += 1
                if any(kw in text for kw in ["GST", "CGST", "SGST", "TAX"]):
                    tax_keywords_count += 1
                for semantic_type, weight in self._cell_votes(text).items():
                    vote_totals[semantic_type] += weight

            best_type, best_score = max(vote_totals.items(), key=lambda kv: kv[1])
            sorted_votes = sorted(vote_totals.values(), reverse=True)
            runner_up = sorted_votes[1] if len(sorted_votes) > 1 else 0.0
            conf = (best_score - runner_up) / max(1.0, sum(vote_totals.values()))
            conf = max(0.0, min(0.95, conf))

            if best_score <= 0:
                best_type = ColumnSemantics.UNKNOWN

            if best_type == ColumnSemantics.AMOUNT:
                preliminary_amount_cols.append(c_id)

            analysis_results[c_id] = {
                "type": best_type,
                "confidence": round(conf, 3),
                "metrics": {
                    "sample_size": total_count,
                    "numeric_density": round(numeric_count / total_count, 2),
                    "decimal_density": round(decimal_count / total_count, 2),
                    "tax_signal": tax_keywords_count > 0,
                    "weighted_votes": {k: round(v, 3) for k, v in vote_totals.items()},
                    "inferred_from_item_rows_only": columns_inferred_from_item_rows_only
                }
            }

        if len(preliminary_amount_cols) > 1:
            col_order = {c.col_id: i for i, c in enumerate(region.columns)}
            rightmost_amount_col = max(preliminary_amount_cols, key=lambda cid: col_order.get(cid, -1))
            for cid in preliminary_amount_cols:
                if cid != rightmost_amount_col:
                    analysis_results[cid]["type"] = ColumnSemantics.RATE
                    analysis_results[cid]["metrics"]["amount_column_demoted_to_rate"] = True

        analysis_results["_inference_summary"] = {
            "columns_inferred_from_item_rows_only": columns_inferred_from_item_rows_only,
            "item_rows_used": len(item_row_ids),
        }
        return analysis_results

    def enrich_region_metadata(self, region: TableRegion) -> Dict[str, Any]:
        """
        Annotates semantic outliers without deleting OCR text.
        """
        results = self.analyze_table_columns(region)

        QTY_WHITELIST = r"^[ \d\+\*xX\.,\s\(\)-]+$"
        AMOUNT_WHITELIST = r"^[ \d\.,₹$RS]+$" # Strict finance whitelist

        outliers = 0
        hard_deleted = 0
        for cid, data in results.items():
            if cid.startswith("_"):
                continue
            ctype = data["type"]
            if ctype in (ColumnSemantics.QUANTITY, ColumnSemantics.AMOUNT):
                target_regex = QTY_WHITELIST if ctype == ColumnSemantics.QUANTITY else AMOUNT_WHITELIST

                q_cells = [c for c in region.cells if c.col_id == cid]
                for c in q_cells:
                    if not c.text: continue
                    clean_t = c.text.strip()
                    if not re.match(target_regex, clean_t, re.IGNORECASE):
                        if c.original_text is None:
                            c.original_text = c.text
                        c.semantic_outlier = True
                        c.semantic_outlier_reason = f"non_conforming_{ctype}_cell"
                        outliers += 1

        if outliers > 0:
            logger.warning(f"[SEMANTIC QUARANTINE] Marked {outliers} non-conforming cells as semantic outliers.")
        results["_rejection_summary"] = {
            "semantic_rejection_count": outliers,
            "semantic_outlier_count": outliers,
            "hard_deleted_cells_count": hard_deleted,
        }

        # Summarize final structure
        type_counts = {}
        for cid, data in results.items():
            if cid.startswith("_"):
                continue
            ctype = data["type"]
            type_counts[ctype] = type_counts.get(ctype, 0) + 1
            
        logger.info(f"[COLUMN SEMANTICS] Post-Hardening Breakdown: {type_counts}")
        return results
