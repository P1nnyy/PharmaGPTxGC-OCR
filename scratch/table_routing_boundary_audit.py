import os
import sys
import json
import re
from pathlib import Path
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import required pipeline modules
from services.ocr_engine import process_image
from services.layout_pipeline.geometry import process_blocks
from services.layout_pipeline.skew import apply_skew_normalization
from services.tsr.heuristic_tsr import HeuristicTSREngine
from services.topology.column_stabilizer import ColumnStabilizer
from services.layout_pipeline.ioa_mapping import map_tokens_to_cells
from services.layout_pipeline.multiline_merging import merge_multiline_table_rows, update_row_stability_scores
from services.table_classifier import TableClassifier, route_tables, TableType
from services.layout_pipeline.semantic_column_classifier import SemanticColumnClassifier

def check_evidence(tr):
    """Gathers all cell texts and maps keyword evidence groups."""
    texts = [cell.text.lower() for cell in tr.cells if cell.text]
    full_text = " ".join(texts)
    
    # Check keywords for groups
    has_product = any(w in full_text for w in ["product", "item", "name", "medicine", "description", "particulars", "drug", "brand"])
    has_batch = any(w in full_text for w in ["batch", "b.no", "b.n", "lot", "b/n", "bno"])
    has_expiry = any(w in full_text for w in ["exp", "expiry", "exp.date", "expdate"])
    has_qty = any(w in full_text for w in ["qty", "quantity", "free", "scheme", "sch", "qnty"])
    has_rate = any(w in full_text for w in ["rate", "ptr", "mrp", "price", "rate/unit", "unit rate"])
    has_amount = any(w in full_text for w in ["amount", "value", "net", "amt"])
    has_gst = any(w in full_text for w in ["hsn", "gst", "tax", "hsn/sac", "taxable"])
    
    evidence_groups = []
    if has_product: evidence_groups.append("product")
    if has_batch: evidence_groups.append("batch")
    if has_expiry: evidence_groups.append("expiry")
    if has_qty: evidence_groups.append("qty")
    if has_rate: evidence_groups.append("rate")
    if has_amount: evidence_groups.append("amount")
    if has_gst: evidence_groups.append("hsn/gst")
    
    return {
        "groups": evidence_groups,
        "has_product": has_product,
        "has_batch": has_batch,
        "has_expiry": has_expiry,
        "has_qty": has_qty,
        "has_rate": has_rate,
        "has_amount": has_amount,
        "has_gst": has_gst,
        "full_text_sample": full_text[:200]
    }

def classify_candidate(tr, coverage_ratio, evidence):
    """Applies audit labels to table candidate regions."""
    col_count = len(tr.columns)
    
    has_product = evidence["has_product"]
    has_batch = evidence["has_batch"]
    has_expiry = evidence["has_expiry"]
    has_qty = evidence["has_qty"]
    has_rate = evidence["has_rate"]
    has_amount = evidence["has_amount"]
    has_gst = evidence["has_gst"]
    
    core_groups = sum([has_product, has_batch, has_expiry, has_qty, has_rate, has_amount])
    
    is_full_width = (col_count >= 6) and (coverage_ratio >= 0.60) and (core_groups >= 3)
    is_collapsed = (col_count <= 3) or (not has_rate and not has_amount)
    is_footer_tax = has_gst and not (has_product or has_batch)
    
    labels = []
    if is_full_width:
        labels.append("full_width_candidate")
    if is_collapsed:
        labels.append("collapsed_slice")
    if is_footer_tax:
        labels.append("possible_footer_or_tax_slice")
        
    return labels if labels else ["unknown"]

def run_audit():
    target_images = [
        "test_images/9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG",
        "test_images/cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG"
    ]
    
    results = {}
    
    for img_path in target_images:
        path = REPO_ROOT / img_path
        filename = path.name
        print(f"Auditing {filename}...")
        
        # Load image & run OCR
        image = Image.open(path).convert("RGB")
        page_width, page_height = image.size
        
        ocr_result = process_image(image)
        blocks = ocr_result.get("blocks", [])
        
        # Assign IDs to blocks
        for i, b in enumerate(blocks):
            if "id" not in b:
                b["id"] = f"block_{i}"
        
        # Normalize and run geometry pipeline
        ocr_blocks = process_blocks(blocks)
        ocr_blocks = apply_skew_normalization(ocr_blocks)
        
        # TSR Table Detection
        heuristic_engine = HeuristicTSREngine()
        table_regions, tsr_metadata = heuristic_engine.detect_tables(ocr_blocks)
        
        # Run stabilization, cell mapping, and multiline row merging
        stabilizer = ColumnStabilizer()
        for tr in table_regions:
            stabilizer.stabilize_region(tr)
        map_tokens_to_cells(ocr_blocks, table_regions)
        
        for i in range(len(table_regions)):
            tr = table_regions[i]
            tr, _ = merge_multiline_table_rows(tr, ocr_blocks)
            tr = update_row_stability_scores(tr, ocr_blocks)
            table_regions[i] = tr
            
        # Classify and route
        classifier_engine = TableClassifier()
        classifications = classifier_engine.classify_region_list(table_regions)
        table_routing_diagnostics = getattr(classifier_engine, "last_routing_diagnostics", {})
        table_bundle = route_tables(table_regions, classifications, diagnostics=table_routing_diagnostics)
        
        selected_main_table_id = table_bundle.main_table.table_id if table_bundle.main_table else "None"
        
        # Analyze each candidate
        candidates_data = []
        best_candidate = None
        best_coverage = 0.0
        
        semantic_classifier = SemanticColumnClassifier()
        
        for idx, tr in enumerate(table_regions):
            classification = classifications[idx]
            is_selected = (tr.table_id == selected_main_table_id)
            
            # Geometry
            x_min = tr.geometry.min_x if tr.geometry else 0.0
            x_max = tr.geometry.max_x if tr.geometry else 0.0
            x_width = x_max - x_min
            y_min = tr.geometry.min_y if tr.geometry else 0.0
            y_max = tr.geometry.max_y if tr.geometry else 0.0
            y_height = y_max - y_min
            x_coverage = x_width / page_width if page_width else 0.0
            
            # Counts
            row_count = len(tr.rows)
            col_count = len(tr.columns)
            cell_count = len(tr.cells)
            non_empty_cells = sum(1 for c in tr.cells if c.text and c.text.strip())
            
            # Evidence
            evidence = check_evidence(tr)
            labels = classify_candidate(tr, x_coverage, evidence)
            
            # Semantics
            try:
                semantic_res = semantic_classifier.enrich_region_metadata(tr)
                inference_summary = semantic_res.get("_inference_summary", {})
                final_semantics = inference_summary.get("final_column_semantics", {})
            except Exception as e:
                final_semantics = {}
                
            final_semantic_vals = [str(v).lower() for v in final_semantics.values()]
            missing_req_semantics = []
            if "amount" not in final_semantic_vals:
                missing_req_semantics.append("amount")
            if not any(k in final_semantic_vals for k in ["quantity", "qty", "free_quantity"]):
                missing_req_semantics.append("quantity")
            if "rate" not in final_semantic_vals:
                missing_req_semantics.append("rate")
            if not any(k in final_semantic_vals for k in ["product", "drug_name"]):
                missing_req_semantics.append("product")
                
            # Score
            score_details = classifier_engine.score_region_for_main_table(tr)
            routing_score = score_details.get("score", 0.0)
            score_profile = score_details.get("reason", "")
            rejected_reasons = score_details.get("rejected_reasons", [])
            
            cand_info = {
                "table_id": tr.table_id,
                "region_type": tr.region_type.value if tr.region_type else "unknown",
                "source_engine": tr.source_engine,
                "row_count": row_count,
                "column_count": col_count,
                "cell_count": cell_count,
                "non_empty_cell_count": non_empty_cells,
                "x_min": round(x_min, 2),
                "x_max": round(x_max, 2),
                "x_width": round(x_width, 2),
                "y_min": round(y_min, 2),
                "y_max": round(y_max, 2),
                "y_height": round(y_height, 2),
                "page_width": page_width,
                "x_coverage_ratio": round(x_coverage, 4),
                "evidence_groups": evidence["groups"],
                "labels": labels,
                "final_column_semantics": final_semantics,
                "missing_required_semantics": missing_req_semantics,
                "classification": str(classification),
                "score_profile": score_profile,
                "routing_score": routing_score,
                "rejected_reasons": rejected_reasons,
                "is_selected": is_selected
            }
            candidates_data.append(cand_info)
            
            # Keep track of best candidate (full-width)
            if "full_width_candidate" in labels:
                if x_coverage > best_coverage:
                    best_coverage = x_coverage
                    best_candidate = cand_info
                    
        # Determine case label
        has_full_width = any("full_width_candidate" in c["labels"] for c in candidates_data)
        selected_cand_info = next((c for c in candidates_data if c["is_selected"]), None)
        
        if has_full_width:
            if selected_cand_info and "full_width_candidate" in selected_cand_info["labels"]:
                case_label = "CASE_A_ROUTING_FAILURE"
            else:
                case_label = "CASE_A_ROUTING_FAILURE"
        else:
            case_label = "CASE_B_RECONSTRUCTION_FRAGMENTATION"
            
        results[filename] = {
            "selected_main_table_id": selected_main_table_id,
            "selected_rows": selected_cand_info["row_count"] if selected_cand_info else 0,
            "selected_cols": selected_cand_info["column_count"] if selected_cand_info else 0,
            "selected_x_coverage": selected_cand_info["x_coverage_ratio"] if selected_cand_info else 0.0,
            "best_full_width_candidate_id": best_candidate["table_id"] if best_candidate else "None",
            "best_candidate_rows": best_candidate["row_count"] if best_candidate else 0,
            "best_candidate_cols": best_candidate["column_count"] if best_candidate else 0,
            "best_candidate_x_coverage": best_candidate["x_coverage_ratio"] if best_candidate else 0.0,
            "case_label": case_label,
            "candidates": candidates_data
        }
        
    # Write JSON output
    json_report_path = REPO_ROOT / "scratch/table_routing_boundary_audit_results.json"
    with open(json_report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"JSON report written to: {json_report_path}")
    
    # Build and Write Markdown output
    md_lines = [
        "# Table Routing Boundary Audit",
        "",
        "## Executive Summary",
        ""
    ]
    
    # Determine overall executive summary
    overall_case_b = any(res["case_label"] == "CASE_B_RECONSTRUCTION_FRAGMENTATION" for res in results.values())
    overall_case_a = any(res["case_label"] == "CASE_A_ROUTING_FAILURE" for res in results.values())
    
    if overall_case_b:
        md_lines.append("The current failure is likely **reconstruction fragmentation**. No full-width candidate table region encompassing the entire medicine table exists before routing. The medicine table has already been split horizontally or vertically in `row_clustering.py` or `heuristic_tsr.py` prior to the routing step.")
    elif overall_case_a:
        md_lines.append("The current failure is likely **routing failure**. A full-width medicine table candidate exists, but the pipeline classifier selected a collapsed slice or a footer/tax slice instead. The fix should target `table_classifier.py` / routing selection.")
    else:
        md_lines.append("The failure mode is indeterminate due to **insufficient diagnostics**.")
        
    md_lines.extend([
        "",
        "## Per-Invoice Decision",
        "",
        "| filename | selected table id | selected rows x cols | selected x coverage | best full-width candidate id | best candidate rows x cols | best candidate x coverage | case label | conclusion |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    ])
    
    for fname, res in results.items():
        conclusion = ""
        if res["case_label"] == "CASE_B_RECONSTRUCTION_FRAGMENTATION":
            conclusion = "No full-width candidate region exists. Table is fragmented before routing."
        elif res["case_label"] == "CASE_A_ROUTING_FAILURE":
            conclusion = f"Full-width candidate {res['best_full_width_candidate_id']} was bypassed for collapsed slice {res['selected_main_table_id']}."
            
        md_lines.append(
            f"| {fname} | {res['selected_main_table_id']} | {res['selected_rows']}x{res['selected_cols']} | {res['selected_x_coverage']} | "
            f"{res['best_full_width_candidate_id']} | {res['best_candidate_rows']}x{res['best_candidate_cols']} | {res['best_candidate_x_coverage']} | "
            f"{res['case_label']} | {conclusion} |"
        )
        
    md_lines.extend([
        "",
        "## All Candidate Table Regions",
        ""
    ])
    
    for fname, res in results.items():
        md_lines.extend([
            f"### Invoice: {fname}",
            "",
            "| candidate table id | rows x cols | x coverage | non-empty cells | labels | routing score | score profile | selected? |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"
        ])
        for c in res["candidates"]:
            labels_str = ", ".join(c["labels"]) or "none"
            selected_str = "**Yes**" if c["is_selected"] else "No"
            md_lines.append(
                f"| {c['table_id']} | {c['row_count']}x{c['column_count']} | {c['x_coverage_ratio']} | {c['non_empty_cell_count']}/{c['cell_count']} | "
                f"{labels_str} | {c['routing_score']} | {c['score_profile']} | {selected_str} |"
            )
        md_lines.append("")
        
    md_lines.extend([
        "## Final Recommendation",
        ""
    ])
    
    if overall_case_b:
        md_lines.append("### Recommended Action: Patch `row_clustering.py` / `heuristic_tsr.py` reconstruction")
        md_lines.append("Since no full-width table candidate exists before routing, the table is already fragmented. We must:")
        md_lines.append("1. Fix row grouping logic in `row_clustering.py` to prevent horizontal splitting when small page skew is present.")
        md_lines.append("2. Prevent over-segmentation in `heuristic_tsr.py` when consecutive rows have slight classification variations (e.g., intermediate 'Unknown' rows).")
    else:
        md_lines.append("### Recommended Action: Patch `table_classifier.py` / spatial_reconstruction routing guardrails")
        md_lines.append("Since a valid full-width candidate is available but bypassed, we must adjust scoring weights and penalties in `table_classifier.py` to avoid selecting collapsed slices.")
        
    md_lines.extend([
        "",
        "## Evidence",
        "",
        "- Target Images processed:",
        "  1. `test_images/9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG`",
        "  2. `test_images/cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG`",
        "- The audit evaluated candidate TableRegions generated dynamically using production geometry extraction, skew normalization, heuristic TSR detection, cell mapping, and multiline merging.",
        f"- Full JSON results are saved in `scratch/table_routing_boundary_audit_results.json`."
    ])
    
    md_report_path = REPO_ROOT / "scratch/table_routing_boundary_audit_results.md"
    md_report_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Markdown report written to: {md_report_path}")

if __name__ == "__main__":
    run_audit()
