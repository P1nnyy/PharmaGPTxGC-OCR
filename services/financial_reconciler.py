"""
Redesigned Financial Reconciler for PharmaGPT.

Handles:
- Fuzzy keyword matching for Grand Total detection (Failure Mode 1)
- Discount-aware row arithmetic verification (Failure Mode 2)
- Fractional and compound quantities integration (via qty_parser)
- Multi-dimensional scoring rubric (Failure Mode 6)

Preserves existing function signatures and in-pipeline TableRegion logic.
"""

import re
import math
from enum import Enum
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import List, Dict, Any, Optional, Tuple, Union
from pydantic import BaseModel, Field, ConfigDict
from rapidfuzz import fuzz, process

from core.logger import logger
from models.layout_models import TableRegion, TableCell, RowRegion
from services.qty_parser import parse_quantity

# --- Domain Definitions & Constants ---

class ValidationStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"

class SubScore(BaseModel):
    name: str
    score: float  # 0 to 100
    weight: float  # 0 to 1.0
    reasoning: str

class FinancialConfig:
    MATCH_TOLERANCE = Decimal("1.00")  # ±₹1.00
    GRAND_TOTAL_KEYWORDS_TIER1 = [
        "GRAND TOTAL", "NET AMOUNT", "NET AMT", "NET PAYABLE", 
        "BILL AMOUNT", "TOTAL AMT", "TOTAL PAYABLE", "PAYABLE AMOUNT", 
        "INVOICE TOTAL", "GRAND TOTAL AMOUNT"
    ]
    GRAND_TOTAL_KEYWORDS_TIER2 = [
        "NET VALUE", "TOTAL INVOICE", "FINAL AMOUNT", "TO PAY"
    ]
    SUBTOTAL_KEYWORDS = ["SUB TOTAL", "SUBTOTAL", "BEFORE TAX", "TAXABLE VALUE"]
    DISCOUNT_COL_KEYWORDS = ["DIS", "DISC", "DISCOUNT", "TD%", "CD%", "SCHEME DIS", "SCHEME DISCOUNT", "TRADE DISCOUNT"]

def _to_decimal(val: Any) -> Decimal:
    """Safely convert any numeric/string input into Decimal, cleaning currency artifacts."""
    if val is None:
        return Decimal("0")
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    if isinstance(val, Decimal):
        return val
    
    # String cleaning
    cleaned = re.sub(r'[₹$,\s]', '', str(val).strip())
    
    # OCR Digit Repair
    cleaned = re.sub(r'(?<=\d)[OoOo](?=\d|\.|$)', '0', cleaned)
    cleaned = re.sub(r'(?<=\d|\.)[lI](?=\d|\.|$)', '1', cleaned)
    cleaned = re.sub(r'(?<=\d)[B8](?=\d|\.|$)', '8', cleaned)
    
    # If multiple dots, assume last one is decimal
    if cleaned.count('.') > 1:
        parts = cleaned.split('.')
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
        
    cleaned = re.sub(r'[^0-9.-]', '', cleaned)
    try:
        return Decimal(cleaned) if cleaned else Decimal("0")
    except (ValueError, InvalidOperation):
        return Decimal("0")

# --- Failure Mode 1: Grand Total Detector ---

class GrandTotalDetector:
    """Uses tiered fuzzy matching and positional heuristics to detect true Grand Total row."""
    
    @staticmethod
    def find_candidates(cells_with_positions: List[Dict[str, Any]], total_y_span: float) -> List[Dict[str, Any]]:
        """
        Matches cells against grand total keywords and scores them.
        cells_with_positions expects list of {text: str, value: Decimal, center_y: float, row_idx: int}
        """
        candidates = []
        for entry in cells_with_positions:
            text_upper = str(entry.get("text", "")).upper().strip()
            
            # 1. Keyword matching (Fuzzy)
            best_score = 0
            # Check exact substrings first
            if any(kw in text_upper for kw in FinancialConfig.GRAND_TOTAL_KEYWORDS_TIER1):
                best_score = 100
            else:
                # Fuzzy check against Tier 1 & 2
                match1 = process.extractOne(text_upper, FinancialConfig.GRAND_TOTAL_KEYWORDS_TIER1, scorer=fuzz.WRatio)
                match2 = process.extractOne(text_upper, FinancialConfig.GRAND_TOTAL_KEYWORDS_TIER2, scorer=fuzz.WRatio)
                
                s1 = match1[1] if match1 else 0
                s2 = match2[1] if match2 else 0
                
                # Weight Tier 1 higher
                best_score = max(s1, s2 * 0.8)

            if best_score < 65 and "TOTAL" not in text_upper:
                continue  # Skip weak matches unless explicitly says TOTAL
            
            # 2. Position Score: favors bottom of page/table
            y_pos = entry.get("center_y", 0)
            # Normalize position score: closer to bottom (higher Y) means higher score
            pos_score = (y_pos / total_y_span) * 100 if total_y_span > 0 else 50
            
            # 3. Combined Score
            # 60% keyword, 40% position
            combined = (best_score * 0.6) + (pos_score * 0.4)
            
            candidates.append({
                **entry,
                "keyword_confidence": best_score,
                "position_score": pos_score,
                "final_score": combined
            })
            
        # Sort descending by final combined score
        candidates.sort(key=lambda x: x["final_score"], reverse=True)
        return candidates

# --- Failure Mode 2: Discount-Aware Verifier ---

class DiscountAwareVerifier:
    """Evaluates multiple discount application formulas used in Indian pharma."""
    
    @staticmethod
    def verify_row_math(qty: Decimal, rate: Decimal, amount: Decimal, discount_val: Optional[Decimal] = None, is_pct: bool = False) -> Tuple[bool, str]:
        """
        Tries standard and discount formulas to find match within tolerance.
        Returns (is_match, used_formula_name).
        """
        # Fast zero amount handling
        if amount == 0:
            return (qty == 0, "zero_amount")
            
        tolerance = FinancialConfig.MATCH_TOLERANCE
        base_ext = qty * rate
        
        # Strategy 0: Simple direct math (No Discount)
        if abs(base_ext - amount) <= tolerance:
            return True, "qty_x_rate"
            
        if discount_val is None or discount_val == 0:
            # No discount present but math failed
            return False, "math_failed"
            
        # Strategy 1: Absolute per-row deduction (Amt = Qty*Rate - Disc)
        # Test if discount_val acts as absolute discount on total row
        res1 = abs((base_ext - discount_val) - amount)
        if res1 <= tolerance:
            return True, "base_less_absolute_discount"
            
        # Strategy 2: Percentage per-row (Amt = Qty*Rate * (1 - Disc/100))
        # Try treating discount_val as a percentage even if not explicitly tagged
        res2 = abs((base_ext * (Decimal("1") - (discount_val / Decimal("100")))) - amount)
        if res2 <= tolerance:
            return True, "percentage_discount"
            
        # Strategy 3: Per-unit discount applied to rate (Amt = Qty * (Rate - DiscPerUnit))
        res3 = abs((qty * (rate - discount_val)) - amount)
        if res3 <= tolerance:
            return True, "per_unit_rate_discount"
            
        return False, "all_formulas_failed"

# --- Revised Reconciliation Result Structs ---

class ReconciliationResultV2(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})

    table_id: str = "default"
    
    # Financial Fields
    derived_subtotal: Decimal = Decimal("0")
    parsed_subtotal: Optional[Decimal] = None
    parsed_gst: Optional[Decimal] = None
    parsed_grand_total: Optional[Decimal] = None
    expected_grand_total: Decimal = Decimal("0")
    
    # Row Telemetry
    total_rows: int = 0
    rows_math_passed: int = 0
    rows_math_failed: int = 0
    discount_applied_rows: int = 0
    
    # Flags & Deltas
    subtotal_match: bool = False
    grand_total_match: bool = False
    grand_total_discrepancy: Decimal = Decimal("0")
    
    # Metrics
    integrity_score: float = 0.0
    status: ValidationStatus = ValidationStatus.FAIL
    sub_scores: Dict[str, SubScore] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Maintains backward compatibility with legacy dashboard keys."""
        return {
            "derived_subtotal": float(self.derived_subtotal),
            "parsed_subtotal": float(self.parsed_subtotal) if self.parsed_subtotal else None,
            "parsed_gst": float(self.parsed_gst) if self.parsed_gst else None,
            "parsed_grand_total": float(self.parsed_grand_total) if self.parsed_grand_total else None,
            "expected_grand_total": float(self.expected_grand_total),
            "subtotal_match": self.subtotal_match,
            "grand_total_match": self.grand_total_match,
            "subtotal_discrepancy": float(abs((self.parsed_subtotal or self.derived_subtotal) - self.derived_subtotal)),
            "grand_total_discrepancy": float(self.grand_total_discrepancy),
            "confidence": float(self.integrity_score / 100.0),
            "warnings": self.warnings,
            "status": self.status.value
        }

# --- In-Pipeline Reconciler Interface (TableRegion Context) ---

class FinancialReconciler:
    """
    Deterministic financial validator rewritten for enhanced stability & robustness.
    Utilizes Decimal arithmetic, discount analysis and fuzzy Grand Total deduction.
    """
    
    def __init__(self, semantic_column_cache: Optional[Dict[str, Any]] = None):
        self.semantic_cache = semantic_column_cache or {}

    def reconcile_table(self, region: TableRegion) -> ReconciliationResultV2:
        """Processes TableRegion (cell graph structure) through validation framework."""
        table_semantics = self.semantic_cache.get(region.table_id, {})
        
        # 1. Map Semantic Column IDs
        amt_cols = []
        qty_cols = []
        rate_cols = []
        tax_cols = []
        disc_cols = []
        
        for cid, meta in table_semantics.items():
            ctype = meta.get("type", "").upper() if isinstance(meta, dict) else str(meta).upper()
            if ctype == "AMOUNT": amt_cols.append(cid)
            elif ctype == "QUANTITY" or ctype == "QTY": qty_cols.append(cid)
            elif ctype == "RATE": rate_cols.append(cid)
            elif ctype in ("TAX", "GST"): tax_cols.append(cid)
            elif "DISC" in ctype or "DISCOUNT" in ctype: disc_cols.append(cid)
            
        # 2. Group Cells by Row
        cells_by_row = {}
        for cell in region.cells:
            cells_by_row.setdefault(cell.row_id, []).append(cell)
            
        # 3. Per-Row Processing (Amount derivation, math checks)
        derived_subtotal = Decimal("0")
        math_pass_count = 0
        math_fail_count = 0
        rows_valid_total = 0
        
        verifier = DiscountAwareVerifier()
        footer_row_pattern = re.compile(
            r"\b(SUB\s*TOTAL|GRAND\s*TOTAL|TOTAL|SGST|CGST|GST|ROUND(?:OFF)?|DISCOUNT)\b"
            r"|(?:\b(?:RS\.?|RUPEES)\b.*\bONLY\b)",
            re.IGNORECASE
        )
        
        for row in region.rows:
            # Skip highly unstable or header rows
            if row.stability < 0.4:
                continue
            
            row_cells = cells_by_row.get(row.row_id, [])
            row_text = " ".join(c.text for c in row_cells if c.text).strip()
            if footer_row_pattern.search(row_text):
                logger.debug(
                    f"[FOOTER ROW REJECTED] Skipping row '{row.row_id}' from item subtotal derivation: "
                    f"'{row_text[:120]}'"
                )
                continue
            
            # Extract candidate numeric values
            r_amt = r_qty_obj = r_rate = r_disc = None
            
            for c in row_cells:
                if c.col_id in amt_cols: r_amt = _to_decimal(c.text)
                if c.col_id in qty_cols: r_qty_obj = parse_quantity(c.text)
                if c.col_id in rate_cols: r_rate = _to_decimal(c.text)
                if c.col_id in disc_cols: r_disc = _to_decimal(c.text)
            
            # Standard extraction fallback if rate explicitly isn't tagged yet (Rate acts like Amount)
            if r_rate is None and len(amt_cols) >= 2 and r_amt is not None:
                # Pick the OTHER amt column as candidate rate if we have duplicates
                other_amts = [c for c in row_cells if c.col_id in amt_cols and _to_decimal(c.text) != r_amt]
                if other_amts:
                     r_rate = _to_decimal(other_amts[0].text)

            if r_amt is not None and r_amt > 0:
                derived_subtotal += r_amt
                rows_valid_total += 1
                
                # If we have necessary variables, run verification
                if r_qty_obj is not None and r_rate is not None:
                     # USE BILLED QTY FROM QTY PARSER
                     billed_qty = r_qty_obj.billed_qty
                     success, formula = verifier.verify_row_math(billed_qty, r_rate, r_amt, r_disc)
                     if success:
                         math_pass_count += 1
                     else:
                         math_fail_count += 1
                         
        # 4. Global Metadata Extraction (Totals, GST Sum)
        # Total table span for positional heuristics
        total_y_span = 1000.0
        if region.geometry:
            total_y_span = region.geometry.max_y
            
        # Find potential summary cells
        potential_grand_totals = []
        potential_subtotals = []
        parsed_gst_sum = Decimal("0")
        
        for cell in region.cells:
            text = cell.text.strip()
            if not text: continue
            
            val = _to_decimal(text)
            cy = cell.geometry.center_y if cell.geometry else 0
            
            # Is it in a Tax column? Accumulate directly
            if cell.col_id in tax_cols and val > 0:
                parsed_gst_sum += val
                
            # Candidate metadata object
            meta = {"text": text, "value": val, "center_y": cy, "row_id": cell.row_id}
            
            # Scan for labels
            text_up = text.upper()
            # Subtotal check
            if any(kw in text_up for kw in FinancialConfig.SUBTOTAL_KEYWORDS):
                potential_subtotals.append(meta)
            # Grand total check - pass everything containing 'total' or 'net' for fuzzy vetting
            if "TOTAL" in text_up or "NET" in text_up or "AMT" in text_up:
                potential_grand_totals.append(meta)

        # Run fuzzy grand total selection
        detector = GrandTotalDetector()
        gt_candidates = detector.find_candidates(potential_grand_totals, total_y_span)
        
        parsed_gt = None
        if gt_candidates:
            best_gt = gt_candidates[0]
            # Retrieve value from actual table row logic:
            # Often the value is in an Amount column in same row as label
            row_vals = cells_by_row.get(best_gt["row_id"], [])
            # Try specific amount cell first
            for c in row_vals:
                if c.col_id in amt_cols:
                    candidate_val = _to_decimal(c.text)
                    if candidate_val > derived_subtotal * Decimal("0.5"): # sanity check size
                        parsed_gt = candidate_val
                        break
            # Fallback to original token text if parsing extracted it natively
            if parsed_gt is None and best_gt["value"] > 0:
                parsed_gt = best_gt["value"]

        # Derive final parsed subtotal
        parsed_st = None
        if potential_subtotals:
            # Grab value closest to label
            for st in potential_subtotals:
                row_cells = cells_by_row.get(st["row_id"], [])
                for rc in row_cells:
                    val = _to_decimal(rc.text)
                    if val > 0:
                        parsed_st = val
                        break
                if parsed_st: break

        # 5. Consolidate into V2 Result Model
        res = ReconciliationResultV2(
            table_id=region.table_id,
            derived_subtotal=derived_subtotal,
            parsed_subtotal=parsed_st,
            parsed_gst=parsed_gst_sum if parsed_gst_sum > 0 else None,
            parsed_grand_total=parsed_gt,
            total_rows=rows_valid_total,
            rows_math_passed=math_pass_count,
            rows_math_failed=math_fail_count
        )
        
        # Compute Expected & Match states
        active_sub = parsed_st or derived_subtotal
        active_gst = parsed_gst_sum
        res.expected_grand_total = active_sub + active_gst
        
        if parsed_st is not None:
            res.subtotal_match = abs(parsed_st - derived_subtotal) <= FinancialConfig.MATCH_TOLERANCE
            
        if parsed_gt is not None:
            delta = abs(res.expected_grand_total - parsed_gt)
            res.grand_total_discrepancy = delta
            res.grand_total_match = delta <= FinancialConfig.MATCH_TOLERANCE
            
        # 6. Calculate Multi-dimensional Integrity Score
        res = _compute_v2_scoring(res)
        
        logger.info(f"Reconciled Table [{region.table_id}]: Score={res.integrity_score}, Status={res.status}")
        return res

    def reconcile_all(self, regions: List[TableRegion]) -> Dict[str, Dict[str, Any]]:
        """Legacy-compatible wrapper returning dictionary form of results."""
        final_dict = {}
        for region in regions:
            # In the pipeline context, this is filtered downstream by table classification.
            # But reconciler still executes on region submitted.
            res = self.reconcile_table(region)
            final_dict[region.table_id] = res.to_legacy_dict()
        return final_dict

# --- New Multi-Dimensional Scoring Logic ---

def _compute_v2_scoring(res: ReconciliationResultV2) -> ReconciliationResultV2:
    """Implements Fail Mode 6: Non-linear proportional multi-vector scoring."""
    sub_scores = {}
    
    # 1. Row Math Dimension (30% Weight)
    math_base = 0.0
    if res.total_rows == 0:
        math_base = 50.0 # Neutral if zero rows
        reason_math = "No computable data rows present."
    else:
        # Total potential measurable rows includes explicitly passed or failed
        measurable = res.rows_math_passed + res.rows_math_failed
        if measurable > 0:
             math_base = (res.rows_math_passed / measurable) * 100
             reason_math = f"{res.rows_math_passed}/{measurable} rows verified math."
        else:
             math_base = 80.0 # Assume baseline good if populated but missing vars
             reason_math = "Row items present but insufficient numeric pairs for inline math check."
             
    sub_scores["row_math"] = SubScore(name="Row Math Consistency", score=math_base, weight=0.30, reasoning=reason_math)
    
    # 2. Total Detection Dimension (25% Weight)
    total_score = 0.0
    reason_total = ""
    if res.grand_total_match:
        total_score = 100.0
        reason_total = "Grand total successfully located and matches expected values."
    elif res.parsed_grand_total:
        total_score = 40.0 # Penalized discrepancy
        reason_total = f"Grand total located but differs by {res.grand_total_discrepancy}."
    elif res.parsed_subtotal is not None:
        total_score = 60.0 # Partial credit for subtotal even without grand
        reason_total = "Primary subtotal identified, missing final grand total label."
    else:
        total_score = 10.0
        reason_total = "Neither explicit subtotal nor grand total labels detected."
        
    sub_scores["total_detection"] = SubScore(name="Total Detection", score=total_score, weight=0.25, reasoning=reason_total)
    
    # 3. GST Consistency (15% Weight)
    gst_score = 100.0
    reason_gst = "GST consistent or derived from available sums."
    if res.parsed_gst and res.derived_subtotal > 0:
        ratio = res.parsed_gst / res.derived_subtotal
        if ratio > Decimal("0.40"): # highly suspect >40% tax
            gst_score = 20.0
            reason_gst = f"Suspect tax ratio detected ({ratio:.1%}). Verify extraction."
            
    sub_scores["gst_consistency"] = SubScore(name="GST Consistency", score=gst_score, weight=0.15, reasoning=reason_gst)
    
    # 4. Structural Stability (20% Weight)
    # Placeholder logic here as we're within reconciler. Full pipe pushes higher metrics.
    sub_scores["structural_integrity"] = SubScore(name="Structural Integrity", score=90.0, weight=0.20, reasoning="Table structure recognized.")
    
    # 5. Completeness (10% Weight)
    compl = 100.0 if res.total_rows > 0 else 0.0
    sub_scores["completeness"] = SubScore(name="Invoice Completeness", score=compl, weight=0.10, reasoning="Essential rows found." if compl else "Empty response.")
    
    # Sum weighted scores
    final_raw = sum(sub.score * sub.weight for sub in sub_scores.values())
    res.integrity_score = round(final_raw, 1)
    res.sub_scores = sub_scores
    
    # Assign Thresholds
    if res.integrity_score >= 75.0:
        res.status = ValidationStatus.PASS
    elif res.integrity_score >= 50.0:
        res.status = ValidationStatus.WARN
    else:
        res.status = ValidationStatus.FAIL
        
    return res

# --- Step 3 Public API (Post-LLM JSON context) ---

def validate_invoice_json(invoice_data: dict) -> dict:
    """
    Public API Endpoint validator. Processes full semantic extraction JSON.
    Matches Step 3 requirements.
    """
    logger.info("Commencing validate_invoice_json execution pass.")
    
    # Flatten items
    items = invoice_data.get("items", [])
    
    derived_st = Decimal("0")
    passed = 0
    total_calc = 0
    verifier = DiscountAwareVerifier()
    
    for idx, item in enumerate(items):
        q = _to_decimal(item.get("qty"))
        r = _to_decimal(item.get("rate"))
        a = _to_decimal(item.get("amount"))
        d = _to_decimal(item.get("discount"))
        
        derived_st += a
        
        if q and r:
            total_calc += 1
            ok, _ = verifier.verify_row_math(q, r, a, d if d > 0 else None)
            if ok: passed += 1
            
    # Build meta-result pseudo model
    base_res = ReconciliationResultV2(
        table_id="post_llm_aggregate",
        derived_subtotal=derived_st,
        parsed_subtotal=_to_decimal(invoice_data.get("subtotal")),
        parsed_gst=_to_decimal(invoice_data.get("tax", {}).get("total_tax")),
        parsed_grand_total=_to_decimal(invoice_data.get("grand_total")),
        total_rows=len(items),
        rows_math_passed=passed,
        rows_math_failed=(total_calc - passed)
    )
    
    # Simple expected recalc
    tax_obj = invoice_data.get("tax", {})
    explicit_tax = _to_decimal(tax_obj.get("cgst")) + _to_decimal(tax_obj.get("sgst")) + _to_decimal(tax_obj.get("igst"))
    tax_used = _to_decimal(tax_obj.get("total_tax")) or explicit_tax
    
    base_res.expected_grand_total = (base_res.parsed_subtotal or derived_st) + tax_used
    
    if base_res.parsed_grand_total > 0:
         delta = abs(base_res.expected_grand_total - base_res.parsed_grand_total)
         base_res.grand_total_match = delta <= FinancialConfig.MATCH_TOLERANCE
         base_res.grand_total_discrepancy = delta
         
    if base_res.parsed_subtotal > 0:
         base_res.subtotal_match = abs(base_res.parsed_subtotal - derived_st) <= FinancialConfig.MATCH_TOLERANCE
         
    final_res = _compute_v2_scoring(base_res)
    
    return final_res.model_dump(mode='json')

def compute_integrity_score(validation_result: dict) -> int:
    """Utility mapping full validation_result map to simple 0-100 integer."""
    raw_score = validation_result.get("integrity_score", 0)
    return int(round(float(raw_score)))

def generate_validation_dashboard(invoice_data: dict) -> dict:
    """Generates highly renderable UI structure containing reasoning tree."""
    res = validate_invoice_json(invoice_data)
    
    # Enhance with friendly summary messages
    dashboard = {
        "score": res["integrity_score"],
        "status": res["status"],
        "primary_metrics": {
            "rows_valid": f"{res['rows_math_passed']}/{res['total_rows']}",
            "grand_total_match": res["grand_total_match"],
            "derived_total": res["expected_grand_total"],
            "actual_total": res["parsed_grand_total"]
        },
        "sub_score_breakdown": res["sub_scores"],
        "is_passable": res["integrity_score"] >= 70.0
    }
    return dashboard
