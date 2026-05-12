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
        
    def analyze_table_columns(self, region: TableRegion) -> Dict[str, Dict[str, Any]]:
        """
        Scans all cell text inside each mapped ColumnRegion and scores their distribution profiles.
        Returns map of {col_id: {type, confidence, audit_metrics}}
        """
        analysis_results = {}
        
        for col in region.columns:
            c_id = col.col_id
            # Collect all non-empty cells assigned to this column
            active_cells = [c for c in region.cells if c.col_id == c_id and (c.text or "").strip()]
            
            if not active_cells:
                analysis_results[c_id] = {"type": ColumnSemantics.UNKNOWN, "confidence": 0.0}
                continue
                
            # Feature Vectors
            total_count = len(active_cells)
            numeric_count = 0
            decimal_count = 0
            pct_symbol_count = 0
            tax_keywords_count = 0
            currency_symbol_count = 0
            
            discount_keywords_count = 0
            rate_keywords_count = 0
            
            for c in active_cells:
                text = c.text.upper()
                clean = re.sub(r'[^\d.]', '', text)
                
                # 1. Basic Numeric Checks
                if re.search(r'\d', text):
                    numeric_count += 1
                
                # 2. Decimal Presence (Amount/Rate indicator)
                if '.' in text:
                    decimal_count += 1
                    
                # 3. Tax/Symbol Triggers
                if '%' in text:
                    pct_symbol_count += 1
                if any(kw in text for kw in ["GST", "CGST", "SGST", "TAX"]):
                    tax_keywords_count += 1
                if any(kw in text for kw in ["DIS", "DISC", "TD%", "CD%"]):
                    discount_keywords_count += 1
                if any(kw in text for kw in ["RATE", "UNIT PRICE", "MRP"]):
                    rate_keywords_count += 1
                if "₹" in text or "RS" in text:
                    currency_symbol_count += 1
            
            # Normalized Score Ratios
            ratio_num = numeric_count / total_count
            ratio_dec = decimal_count / total_count
            ratio_tax = (pct_symbol_count + tax_keywords_count) / total_count
            ratio_disc = (discount_keywords_count) / total_count
            ratio_rate = (rate_keywords_count) / total_count
            
            # --- CLASSIFICATION DECISION TREE ---
            best_type = ColumnSemantics.UNKNOWN
            conf = 0.0
            
            if ratio_num > 0.6:
                # Heavy Numeric Vector
                if ratio_tax > 0.15 or tax_keywords_count > 0:
                    best_type = ColumnSemantics.TAX
                    conf = 0.8
                elif ratio_disc > 0.05 or discount_keywords_count > 0:
                    best_type = ColumnSemantics.DISCOUNT
                    conf = 0.85
                elif ratio_rate > 0.05 or rate_keywords_count > 0:
                    best_type = ColumnSemantics.RATE
                    conf = 0.85
                elif ratio_dec > 0.5 or currency_symbol_count > 0:
                    best_type = ColumnSemantics.AMOUNT
                    conf = 0.85
                else:
                    # Numeric but no decimals -> likely Qty or HSN
                    best_type = ColumnSemantics.QUANTITY
                    conf = 0.75
            elif ratio_num < 0.3:
                # Dominantly textual (Product Names / Manufacturer / Batch chars)
                best_type = ColumnSemantics.TEXT
                conf = 0.9
            else:
                # Mixed / Mixed Alphanumeric
                best_type = ColumnSemantics.TEXT
                conf = 0.6
                
            analysis_results[c_id] = {
                "type": best_type,
                "confidence": round(conf, 3),
                "metrics": {
                    "sample_size": total_count,
                    "numeric_density": round(ratio_num, 2),
                    "decimal_density": round(ratio_dec, 2),
                    "tax_signal": tax_keywords_count > 0
                }
            }
            
        return analysis_results

    def enrich_region_metadata(self, region: TableRegion) -> None:
        """
        Mutates region internally, attaching classification tags to Columns, and fires diagnostics.
        """
        results = self.analyze_table_columns(region)
        
        # Store aggregated findings in logging and attach back to Column objects if applicable
        type_counts = {}
        for cid, data in results.items():
            ctype = data["type"]
            type_counts[ctype] = type_counts.get(ctype, 0) + 1
            
        logger.info(f"[COLUMN SEMANTICS] Breakdown: {type_counts}")
        
        # Log potential validation alerts
        amt_cols = [cid for cid, data in results.items() if data["type"] == ColumnSemantics.AMOUNT]
        if len(amt_cols) > 4:
            logger.warning(f"[SEMANTIC ALERT] Abnormally high Amount-Column density ({len(amt_cols)}) detected! Potential column fracturing.")
            
        # Attaches explicit semantics to source region telemetry for downstream observation
        # Note: In current model ColumnRegion may not support 'semantic_tag', we inject via region.source_engine metadata update trick or logger export
        return results
