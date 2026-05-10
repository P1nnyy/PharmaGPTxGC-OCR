import re
from typing import List, Dict, Any
from core.logger import logger
from models.layout_models import TableRegion

class TopologyStabilityEngine:
    """
    Computes live reconstruction confidence ratings based purely on internal 
    mathematical cohesion and structural hygiene.
    """
    
    def __init__(self):
        pass
        
    def compute_stability(self, regions: List[TableRegion]) -> Dict[str, Any]:
        score = 100.0
        deductions = []
        math_confirmed_lines = 0
        suspicious_density_lines = 0
        
        for region in regions:
            # Regroup by logical Row
            row_buckets = {}
            for cell in region.cells:
                rid = cell.row_id
                if rid not in row_buckets: row_buckets[rid] = []
                row_buckets[rid].append(cell)
                
            for rid, cells in row_buckets.items():
                row_values = []
                for c in cells:
                    if not c.text: continue
                    # Harvest valid clean numbers
                    nums = re.findall(r'\d[\d\s,]*\.\d{2}', c.text)
                    for n in nums:
                        try:
                            cleaned = re.sub(r'[^\d.]', '', n)
                            if cleaned:
                                row_values.append(float(cleaned))
                        except:
                            pass
                            
                # Check 1: Suspicious Item Concentration (Column Collision)
                if len(row_values) > 4:
                    suspicious_density_lines += 1
                    
                # Check 2: Live Row-Level Algebra Affirmation (Qty * Rate = Net)
                if len(row_values) >= 3:
                    sv = sorted(row_values)
                    confirmed = False
                    # Quick n^3 test on small sets (usually < 5 items)
                    for i in range(len(sv)):
                        for j in range(i + 1, len(sv)):
                            for k in range(j + 1, len(sv)):
                                if abs((sv[i] * sv[j]) - sv[k]) < 0.5:
                                    confirmed = True
                                    break
                    if confirmed:
                        math_confirmed_lines += 1

        # Compute deductions
        if suspicious_density_lines > 0:
            penalty = suspicious_density_lines * 8
            score -= penalty
            deductions.append(f"Detected {suspicious_density_lines} fractured rows with colliding numbers")
            
        # Small boost for consistent rows up to max
        boost = min(20.0, math_confirmed_lines * 5.0)
        # Neutralization if zero math proven on large grids
        if math_confirmed_lines == 0 and score > 90:
            score -= 10.0 # Penalty for zero mathematical affirmation on structural assertions
            deductions.append("Zero mathematical affirmation found across table rows.")

        final_score = max(0.0, min(100.0, score + boost))
        
        status = "STABLE"
        if final_score < 75.0:
            status = "UNSTABLE"
            logger.warning(f"[TOPOLOGY UNSTABLE] Confidence dropped to {final_score:.1f} due to structural integrity conflicts.")
        
        return {
            "stability_score": round(final_score, 2),
            "state": status,
            "diagnostics": {
                "confirmed_math_rows": math_confirmed_lines,
                "fractured_rows": suspicious_density_lines,
                "warnings": deductions
            }
        }
