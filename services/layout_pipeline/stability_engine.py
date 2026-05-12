"""
Enhanced Topology Stability Engine.
Replaces catastrophic binary confidence collapse with composite structured metrics.
Fulfills Task 4: Topology Confidence Redesign.
"""

import re
import statistics
import structlog
from typing import List, Dict, Any
from models.layout_models import TableRegion, ColumnRegion

log = structlog.get_logger()

class TopologyStabilityEngine:
    """
    Generates robust multi-vector confidence scoring representing absolute 
    deterministic topological health.
    """
    
    def compute_stability(self, regions: List[TableRegion]) -> Dict[str, int]:
        """
        Aggregates multi-dimensional reliability vectors across visible table layouts.
        Returns dict format mapping to requirement scale 0-100.
        """
        if not regions:
            return {
                "overall": 0,
                "column_stability": 0,
                "row_integrity": 0,
                "ownership_confidence": 0,
                "anchor_consistency": 0
            }
            
        c_stability_scores = []
        r_integrity_scores = []
        ownership_scores = []
        anchor_scores = []
        
        for region in regions:
            # 1. COLUMN STABILITY VECTOR
            # Signals: Moderate total count, symmetric geometries
            col_count = len(region.columns)
            c_score = 100.0
            if col_count > 12:
                c_score -= (col_count - 12) * 5.0 # Penalize excessive fracturing
            elif col_count < 3:
                c_score -= 20.0 # Too narrow/dead grid
            
            # Check width distribution variance
            if len(region.columns) > 2:
                 widths = [(c.geometry.max_x - c.geometry.min_x) for c in region.columns if c.geometry]
                 if widths:
                      med_w = statistics.median(widths)
                      # Tiny columns drag stability down
                      narrow_count = sum(1 for w in widths if w < med_w * 0.15)
                      c_score -= (narrow_count * 15.0)
            
            c_stability_scores.append(max(0.0, c_score))
            
            # 2. ROW INTEGRITY VECTOR
            # Signals: Direct pull from RowRegion.stability and logical row density
            row_stabilities = [getattr(r, 'stability', 1.0) for r in region.rows]
            r_score = statistics.mean(row_stabilities) * 100.0 if row_stabilities else 50.0
            
            # Penalize if table has literally 0 rows
            if not region.rows:
                 r_score = 0.0
            r_integrity_scores.append(r_score)
            
            # 3. OWNERSHIP CONFIDENCE VECTOR
            # Signals: Ratio of mapped cells which contain text, vs empty grid spaces
            total_slots = len(region.rows) * len(region.columns)
            populated_cells = len([c for c in region.cells if c.text and c.text.strip()])
            
            coverage = populated_cells / max(1.0, total_slots)
            # Ideal invoice density is usually 0.4 - 0.8
            if coverage < 0.2:
                 own_score = 40.0 # Massive empty grid noise
            elif coverage > 0.9:
                 own_score = 100.0 # Extremely full data grid
            else:
                 own_score = 60.0 + (coverage * 40.0)
            
            # Factor in topological engine confidence from model
            own_score = (own_score + (region.topology_confidence * 100.0)) / 2.0
            ownership_scores.append(own_score)
            
            # 4. ANCHOR CONSISTENCY VECTOR
            # Measure right edge delta clustering
            # For amount cells, retrieve right edge alignment vs expected wall
            numeric_cells = [c for c in region.cells if c.text and re.search(r'\d', c.text)]
            if not numeric_cells:
                 a_score = 70.0 # Neutral fallback
            else:
                 # Group cells by column to look at right alignment variance
                 col_groups = {}
                 for c in numeric_cells:
                      col_groups.setdefault(c.col_id, []).append(c)
                 
                 variances = []
                 for cid, cell_list in col_groups.items():
                      if len(cell_list) < 2: continue
                      rights = [c.geometry.max_x for c in cell_list if c.geometry]
                      if len(rights) >= 2:
                           variances.append(statistics.stdev(rights))
                 
                 if not variances:
                      a_score = 85.0 # Stable defaults
                 else:
                      avg_stdev = sum(variances) / len(variances)
                      # Lower stdev (tight align) = higher score.
                      # Penalty profile: 0px = 100, 30px = 70, 60px = 40
                      a_score = max(30.0, 100.0 - (avg_stdev * 1.0))
            anchor_scores.append(a_score)
            
        # FINAL AGGREGATION (Mean across primary regions)
        c_stb = int(sum(c_stability_scores) / len(c_stability_scores))
        r_int = int(sum(r_integrity_scores) / len(r_integrity_scores))
        own_c = int(sum(ownership_scores) / len(ownership_scores))
        anc_c = int(sum(anchor_scores) / len(anchor_scores))
        
        # Cap 0-100
        c_stb = max(0, min(100, c_stb))
        r_int = max(0, min(100, r_int))
        own_c = max(0, min(100, own_c))
        anc_c = max(0, min(100, anc_c))
        
        # Compute Weighted Overall
        # Weights prioritize Row Stability (35%) and Column Logic (25%)
        overall = int((c_stb * 0.25) + (r_int * 0.35) + (own_c * 0.20) + (anc_c * 0.20))
        
        results = {
            "overall": overall,
            "column_stability": c_stb,
            "row_integrity": r_int,
            "ownership_confidence": own_c,
            "anchor_consistency": anc_c
        }
        
        log.info("topology_stability_evaluated", scores=results)
        
        return results
