"""
Table Classification and Routing Engine.
Enhanced with deterministic dominant-table scoring based on Positive/Negative signal profiles.
Fulfills Task 1 & 2 requirements.
"""

import re
import structlog
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from models.layout_models import TableRegion, RegionType

log = structlog.get_logger()

class TableType(str, Enum):
    MAIN_INVOICE_TABLE = "MAIN_INVOICE_TABLE"
    GST_SUMMARY_TABLE = "GST_SUMMARY_TABLE"
    SCHEME_TABLE = "SCHEME_TABLE"
    CREDIT_NOTE_TABLE = "CREDIT_NOTE_TABLE"
    METADATA_TABLE = "METADATA_TABLE"
    UNKNOWN = "UNKNOWN"

class InvoiceTableBundle(BaseModel):
    """Routing container holding organized categorized table groups."""
    main_table: Optional[TableRegion] = None
    gst_summary: List[TableRegion] = Field(default_factory=list)
    scheme_items: List[TableRegion] = Field(default_factory=list)
    credit_notes: List[TableRegion] = Field(default_factory=list)
    metadata_tables: List[TableRegion] = Field(default_factory=list)
    routing_diagnostics: Dict[str, Any] = Field(default_factory=dict)

class TableClassifier:
    """
    Deterministic dominant-table scorer utilizing positive numeric flow 
    and negative metadata penalties.
    """

    FOOTER_SUMMARY_PHRASES = (
        "GRAND TOTAL",
        "NET AMOUNT",
        "NET AMT",
        "NET PAYABLE",
        "TOTAL QTY",
        "TOTAL ITEMS",
        "CURRENT BALANCE",
        "AUTHORISED SIGNATORY",
        "AUTHORIZED SIGNATORY",
        "SGST PAYBLE",
        "CGST PAYBLE",
        "SGST PAYABLE",
        "CGST PAYABLE",
        "ROUND OFF",
        "ROUNDOFF",
        "GROSS AMOUNT",
        "LESS DISCOUNT",
        "GST SUMMARY",
        "SALE TAX",
        "TAXFREE",
        "SUB TOTAL",
        "TOTAL GST",
        "CR/DR NOTE",
    )
    SPARSE_MAIN_REJECTION_PHRASES = (
        "TOTAL QTY",
        "GRAND TOTAL",
        "NET AMOUNT",
        "AUTHORISED SIGNATORY",
        "AUTHORIZED SIGNATORY",
        "SGST PAYBLE",
        "CGST PAYBLE",
        "GROSS AMOUNT",
        "LESS DISCOUNT",
        "ROUND OFF",
    )

    PRODUCT_MARKER_RE = re.compile(
        r"\b(TAB|CAP|CAPS|INJ|SYP|SYRUP|SUSP|DROPS?|CREAM|OINT|GEL|"
        r"LOTION|ML|MG|GM|MCG|DT|XR|SR|MR)\b",
        re.IGNORECASE,
    )
    BATCH_RE = re.compile(r"\b(?=[A-Z0-9-]{5,20}\b)(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9-]+\b")
    EXPIRY_RE = re.compile(r"\b\d{1,2}[/-]\d{2,4}\b")
    HSN_RE = re.compile(r"\b\d{6,8}\b")
    MONEY_RE = re.compile(r"\b\d[\d,]*\.\d{1,3}\b")
    QTY_RE = re.compile(r"\b\d{1,4}(?:\.\d{1,3})?(?:\+\d{1,4}(?:\.\d{1,3})?)?\b")

    def _cells(self, region: TableRegion) -> List[Any]:
        return [c for c in region.cells if c.text and c.text.strip()]

    def _full_text(self, cells: List[Any]) -> str:
        return " ".join(c.text for c in cells if c.text).upper()

    def _footer_phrase_hits(self, full_text: str) -> List[str]:
        return [phrase for phrase in self.FOOTER_SUMMARY_PHRASES if phrase in full_text]

    def _row_texts(self, region: TableRegion) -> List[str]:
        cells_by_row: Dict[str, List[str]] = {}
        for cell in region.cells:
            if cell.text and cell.text.strip():
                cells_by_row.setdefault(cell.row_id, []).append(cell.text.strip())
        ordered = []
        for row in region.rows:
            text = " ".join(cells_by_row.get(row.row_id, []))
            if text.strip():
                ordered.append(text)
        return ordered

    def _role_counts(self, region: TableRegion) -> Dict[str, int]:
        counts = {
            "item_rows_count": 0,
            "header_rows_count": 0,
            "footer_rows_count": 0,
            "tax_rows_count": 0,
            "metadata_rows_count": 0,
            "unknown_rows_count": 0,
        }
        for row in region.rows:
            role = getattr(row, "row_role", "unknown_row")
            if role == "item_row":
                counts["item_rows_count"] += 1
            elif role == "header_row":
                counts["header_rows_count"] += 1
            elif role == "footer_summary_row":
                counts["footer_rows_count"] += 1
            elif role == "tax_summary_row":
                counts["tax_rows_count"] += 1
            elif role == "metadata_row":
                counts["metadata_rows_count"] += 1
            else:
                counts["unknown_rows_count"] += 1
        return counts

    def _semantic_cache_all_unknown_or_missing(self, region: TableRegion) -> bool:
        semantic_cache = getattr(region, "semantic_column_cache", None) or getattr(region, "column_semantics", None)
        if not semantic_cache:
            return True
        if isinstance(semantic_cache, dict):
            semantic_values = [
                value.get("type") if isinstance(value, dict) else value
                for key, value in semantic_cache.items()
                if not str(key).startswith("_")
            ]
        else:
            semantic_values = list(semantic_cache)
        semantic_values = [str(value).lower() for value in semantic_values if str(value).strip()]
        return not semantic_values or all(value == "unknown" for value in semantic_values)

    def score_region_for_main_table(self, region: TableRegion) -> Dict[str, Any]:
        cells = self._cells(region)
        full_text = self._full_text(cells)
        row_texts = self._row_texts(region)
        row_count = len(region.rows)
        column_count = len(region.columns)
        populated_cells = len(cells)
        if not cells or not region.rows:
            return {
                "table_id": region.table_id,
                "region_type": region.region_type.value if region.region_type else "unknown",
                "source_engine": region.source_engine,
                "score": -1000.0,
                "reason": "empty_or_dead_region",
                "row_count": row_count,
                "column_count": column_count,
                "populated_cells": populated_cells,
                "avg_cells_per_row": 0.0,
                "product_like_rows": 0,
                "batch_pattern_count": 0,
                "expiry_pattern_count": 0,
                "hsn_pattern_count": 0,
                "money_pattern_count": 0,
                "qty_pattern_count": 0,
                "numeric_diverse_rows": 0,
                "footer_phrase_hits": [],
                "sparse_main_rejection_phrase_hits": [],
                "semantic_cache_all_unknown_or_missing": True,
                "anchor_repairability_signal_count": 0,
                "role_counts": self._role_counts(region),
                "rejected_reasons": ["empty_or_dead_region"],
                "product_like_fallback": False,
                "non_footer_fallback": False,
                "sample": "",
            }
        avg_cells_per_row = populated_cells / max(1, row_count)
        role_counts = self._role_counts(region)
        footer_hits = self._footer_phrase_hits(full_text)
        sparse_rejection_phrase_hits = [
            phrase for phrase in self.SPARSE_MAIN_REJECTION_PHRASES if phrase in full_text
        ]
        semantic_cache_all_unknown_or_missing = self._semantic_cache_all_unknown_or_missing(region)

        product_like_rows = 0
        numeric_diverse_rows = 0
        summary_like_rows = 0
        for row_text in row_texts:
            row_upper = row_text.upper()
            row_footer_hits = self._footer_phrase_hits(row_upper)
            if row_footer_hits:
                summary_like_rows += 1

            has_product = bool(self.PRODUCT_MARKER_RE.search(row_upper)) and len(re.findall(r"[A-Z]{3,}", row_upper)) >= 1
            has_numeric = bool(self.MONEY_RE.search(row_upper) or self.QTY_RE.search(row_upper))
            if has_product:
                product_like_rows += 1
            if has_numeric and len(set(re.findall(r"\d+(?:\.\d+)?", row_upper))) >= 2:
                numeric_diverse_rows += 1

        batch_count = len(self.BATCH_RE.findall(full_text))
        expiry_count = len(self.EXPIRY_RE.findall(full_text))
        hsn_count = len(self.HSN_RE.findall(full_text))
        money_count = len(self.MONEY_RE.findall(full_text))
        qty_count = len(self.QTY_RE.findall(full_text))

        score = 0.0
        reasons: List[str] = []
        rejected_reasons: List[str] = []

        if row_count >= 2:
            score += 35.0
            reasons.append("rows_ge_2")
        if row_count >= 5:
            score += 90.0
            reasons.append("rows_ge_5")
        score += min(row_count * 7.0, 90.0)

        if column_count >= 4:
            score += 35.0
            reasons.append("columns_ge_4")
        if column_count >= 8:
            score += 90.0
            reasons.append("columns_ge_8")
        score += min(column_count * 5.0, 70.0)
        score += min(populated_cells * 2.0, 140.0)
        score += min(avg_cells_per_row * 10.0, 80.0)

        if product_like_rows:
            score += product_like_rows * 45.0
            reasons.append("product_like_rows")
        if batch_count:
            score += min(batch_count * 8.0, 80.0)
            reasons.append("batch_patterns")
        if expiry_count:
            score += min(expiry_count * 12.0, 80.0)
            reasons.append("expiry_patterns")
        if hsn_count:
            score += min(hsn_count * 8.0, 60.0)
            reasons.append("hsn_patterns")
        if money_count and numeric_diverse_rows:
            score += min((money_count * 3.0) + (numeric_diverse_rows * 20.0), 140.0)
            reasons.append("numeric_diversity")
        if qty_count >= 2:
            score += min(qty_count * 2.0, 40.0)

        anchor_repairability_signal_count = sum(
            bool(signal)
            for signal in (
                product_like_rows > 0,
                batch_count > 0,
                expiry_count > 0,
                hsn_count > 0,
                numeric_diverse_rows >= 2,
                row_count >= 2 and populated_cells >= 4,
            )
        )
        if anchor_repairability_signal_count >= 3:
            score += 120.0
            reasons.append("anchor_repairability_product_table_potential")

        if region.region_type == RegionType.MEDICINE_TABLE and not footer_hits:
            score += 70.0
            reasons.append("medicine_table_without_footer_phrases")
        elif region.region_type == RegionType.MEDICINE_TABLE:
            score += 15.0

        footer_penalty = len(footer_hits) * 80.0
        if footer_penalty:
            score -= footer_penalty
            rejected_reasons.append("footer_phrase_hits")

        if row_count <= 2 and footer_hits:
            score -= 350.0
            rejected_reasons.append("tiny_footer_summary_table")
        if (
            row_count <= 2
            and column_count <= 2
            and semantic_cache_all_unknown_or_missing
            and footer_hits
            and sparse_rejection_phrase_hits
        ):
            score -= 700.0
            rejected_reasons.append("sparse_selected_main_footer_summary")
        if row_count <= 2 and avg_cells_per_row <= 2.5 and footer_hits:
            score -= 250.0
            rejected_reasons.append("one_or_two_cell_summary_table")
        if summary_like_rows and row_count <= 2:
            score -= summary_like_rows * 160.0
            rejected_reasons.append("summary_like_rows")
        if role_counts["item_rows_count"] == 0 and (role_counts["footer_rows_count"] + role_counts["tax_rows_count"]) > 0:
            score -= 250.0
            rejected_reasons.append("no_item_rows_with_footer_or_tax_roles")
        if region.region_type in {RegionType.TOTALS, RegionType.FOOTER, RegionType.HEADER, RegionType.METADATA}:
            score -= 120.0
            rejected_reasons.append(f"region_type_{region.region_type.value}")
        if row_count <= 1 and product_like_rows == 0:
            score -= 120.0
            rejected_reasons.append("single_row_without_product_evidence")
        if product_like_rows == 0 and footer_hits:
            score -= 400.0
            rejected_reasons.append("footer_without_product_evidence")
        if product_like_rows == 0 and region.region_type != RegionType.MEDICINE_TABLE:
            score -= 180.0
            rejected_reasons.append("no_product_evidence_non_medicine_region")
        if re.search(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", full_text):
            score -= 300.0
            rejected_reasons.append("ifsc_pattern")
        if any(kw in full_text for kw in ("IFSC", "BANK", "A/C", "ACCOUNT NO", "BRANCH")):
            score -= 220.0
            rejected_reasons.append("bank_metadata")
        if any(kw in full_text for kw in ("GST INVOICE", "INVOICE NO", "ACK DATE")) and product_like_rows == 0 and row_count <= 3:
            score -= 180.0
            rejected_reasons.append("invoice_metadata_without_products")

        # Hard safety: previously promoted MAIN labels must not protect footer summaries.
        if "classified_MAIN_INVOICE_TABLE" in str(region.source_engine) and row_count <= 2 and footer_hits:
            score -= 500.0
            rejected_reasons.append("classified_main_but_footer_summary_tiny")

        product_like_fallback = product_like_rows > 0 and not footer_hits
        non_footer_fallback = not footer_hits and populated_cells > 0 and "empty_or_dead_region" not in rejected_reasons
        selected_reason = ",".join(reasons[:6]) or "low_signal_candidate"
        if rejected_reasons:
            selected_reason += f"; penalties={','.join(rejected_reasons[:6])}"

        return {
            "table_id": region.table_id,
            "region_type": region.region_type.value if region.region_type else "unknown",
            "source_engine": region.source_engine,
            "score": round(score, 3),
            "reason": selected_reason,
            "row_count": row_count,
            "column_count": column_count,
            "populated_cells": populated_cells,
            "avg_cells_per_row": round(avg_cells_per_row, 3),
            "product_like_rows": product_like_rows,
            "batch_pattern_count": batch_count,
            "expiry_pattern_count": expiry_count,
            "hsn_pattern_count": hsn_count,
            "money_pattern_count": money_count,
            "qty_pattern_count": qty_count,
            "numeric_diverse_rows": numeric_diverse_rows,
            "footer_phrase_hits": footer_hits,
            "sparse_main_rejection_phrase_hits": sparse_rejection_phrase_hits,
            "semantic_cache_all_unknown_or_missing": semantic_cache_all_unknown_or_missing,
            "anchor_repairability_signal_count": anchor_repairability_signal_count,
            "role_counts": role_counts,
            "rejected_reasons": rejected_reasons,
            "product_like_fallback": product_like_fallback,
            "non_footer_fallback": non_footer_fallback,
            "sample": full_text[:220],
        }

    def compute_dominance_score(self, region: TableRegion) -> float:
        """
        Generates absolute weight scoring of a table region's likelihood 
        of being the Primary Invoice Table.
        """
        return float(self.score_region_for_main_table(region)["score"])

    def classify_single_region(self, region: TableRegion) -> TableType:
        """Backup heuristic categorize for non-dominant auxiliary routing."""
        cells = [c for c in region.cells if c.text and c.text.strip()]
        full_text = " ".join([c.text for c in cells]).upper()
        
        # 1. Credit Note Explicit
        if any(kw in full_text for kw in ("CREDIT NOTE", "CR NOTE", "RETURNED GOODS")):
            return TableType.CREDIT_NOTE_TABLE
            
        # 2. GST Summary specific profiling
        has_tax_label = any(kw in full_text for kw in ("CGST", "SGST", "IGST", "TAXABLE VALUE"))
        if has_tax_label and len(region.rows) <= 5 and "TAB" not in full_text:
            return TableType.GST_SUMMARY_TABLE
            
        # 3. Scheme Table specifically
        if any(kw in full_text for kw in ("SCHEME", "FREE GOOD", "BONUS", "INITIATIVE")):
            return TableType.SCHEME_TABLE
            
        # Default check for tiny metadata
        if len(region.rows) < 3:
            return TableType.METADATA_TABLE
            
        return TableType.UNKNOWN

    def classify_region_list(self, regions: List[TableRegion]) -> List[TableType]:
        """Process bulk list, promoting absolute HIGHEST scorer to MAIN."""
        if not regions:
            self.last_routing_diagnostics = {}
            return []
            
        candidate_scores = []
        for i, r in enumerate(regions):
            details = self.score_region_for_main_table(r)
            details["table_index"] = i
            candidate_scores.append(details)
            
        # Sort by descending score
        scores = sorted(candidate_scores, key=lambda x: x["score"], reverse=True)
        
        classifications = [TableType.UNKNOWN] * len(regions)
        
        # Assign highest scorer as MAIN_INVOICE_TABLE (Gate logic: score must be positive or reasonable)
        top = scores[0]
        top_idx = top["table_index"]
        top_score = top["score"]
        top_disqualified = bool(top["footer_phrase_hits"] and top["product_like_rows"] == 0)
        selected_reason = top.get("reason", "not_selected")
        if top_score > 20.0 and not top_disqualified: # Minimum competence threshold
             classifications[top_idx] = TableType.MAIN_INVOICE_TABLE
             log.info(
                 "dominant_table_selected",
                 table_index=top_idx,
                 table_id=top["table_id"],
                 score=top_score,
                 reason=top["reason"],
             )
        else:
             fallback = next((c for c in scores if c["product_like_fallback"]), None)
             fallback_reason = "fallback_product_like_candidate"
             if fallback is None:
                 fallback = next((c for c in scores if c["non_footer_fallback"]), None)
                 fallback_reason = "fallback_non_footer_candidate"
             if fallback:
                 top = fallback
                 top_idx = fallback["table_index"]
                 top_score = fallback["score"]
                 selected_reason = f"{fallback_reason}; {fallback.get('reason', 'low_signal_candidate')}"
                 classifications[top_idx] = TableType.MAIN_INVOICE_TABLE
                 log.info(
                     "dominant_table_selected",
                     table_index=top_idx,
                     table_id=fallback["table_id"],
                     score=top_score,
                     reason=fallback_reason,
                 )
             else:
                 log.warning("no_dominant_table_met_threshold", max_score=top_score)
        rejected = [
            {
                "table_id": c["table_id"],
                "table_index": c["table_index"],
                "score": c["score"],
                "reasons": c["rejected_reasons"],
                "footer_phrase_hits": c["footer_phrase_hits"],
                "sample": c["sample"],
            }
            for c in scores
            if c["table_index"] != top_idx and c["rejected_reasons"]
        ]
        self.last_routing_diagnostics = {
            "main_table_candidate_scores": scores,
            "selected_main_table_reason": selected_reason,
            "rejected_main_table_candidates": rejected,
            "main_table_role_counts": top.get("role_counts", {}),
            "main_table_footer_phrase_hits": top.get("footer_phrase_hits", []),
        }
             
        # Classify all others as auxiliaries
        for i in range(len(regions)):
            if classifications[i] == TableType.MAIN_INVOICE_TABLE:
                continue
            # Resolve remaining buckets
            aux_type = self.classify_single_region(regions[i])
            classifications[i] = aux_type if aux_type != TableType.UNKNOWN else TableType.METADATA_TABLE
            
        return classifications

def route_tables(regions: List[TableRegion], classifications: List[TableType], diagnostics: Optional[Dict[str, Any]] = None) -> InvoiceTableBundle:
    """Routes table outputs into clean isolated containers."""
    bundle = InvoiceTableBundle(routing_diagnostics=diagnostics or {})
    
    for region, ttype in zip(regions, classifications):
        region.source_engine = f"classified_{ttype.value}"
        
        if ttype == TableType.MAIN_INVOICE_TABLE:
            bundle.main_table = region
        elif ttype == TableType.GST_SUMMARY_TABLE:
            bundle.gst_summary.append(region)
        elif ttype == TableType.SCHEME_TABLE:
            bundle.scheme_items.append(region)
        elif ttype == TableType.CREDIT_NOTE_TABLE:
            bundle.credit_notes.append(region)
        else:
            bundle.metadata_tables.append(region)
            
    log.info("table_routing_finalized", 
             has_main=bundle.main_table is not None, 
             scheme_count=len(bundle.scheme_items),
             gst_count=len(bundle.gst_summary))
             
    return bundle
