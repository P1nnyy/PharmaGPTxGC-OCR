from typing import List, Dict, Any
from core.logger import logger
from utils.debug_visualizer import draw_debug_visualization

from services.layout_pipeline.geometry import process_blocks
from services.layout_pipeline.skew import apply_skew_normalization
from services.layout_pipeline.ioa_mapping import map_tokens_to_cells

from services.tsr.heuristic_tsr import HeuristicTSREngine
from services.tsr.future_tatr import TATR_TSREngine
from services.tsr.future_ppstructure import PPStructure_TSREngine

def get_engine(mode: str):
    if mode == "tatr":
        return TATR_TSREngine()
    elif mode == "ppstructure":
        return PPStructure_TSREngine()
    else:
        return HeuristicTSREngine()

def reconstruct_layout(blocks: List[Dict[str, Any]], debug: bool = False, reconstruct_mode: str = "heuristic", image: Any = None) -> Dict[str, Any]:
    """
    Entry point for document-layout reasoning engine.
    Orchestrates OCR geometry preservation, TSR grid detection, and Cell Mapping.
    """
    logger.info(f"Starting spatial reconstruction on {len(blocks)} blocks (Mode={reconstruct_mode}, Debug={debug})")
    
    # Ensure blocks have IDs for mapping provenance
    for i, b in enumerate(blocks):
        if "id" not in b:
            b["id"] = f"block_{i}"
            
    # Step 1: Compute geometry
    ocr_blocks = process_blocks(blocks)
    
    # Step 2: Skew Normalization
    ocr_blocks = apply_skew_normalization(ocr_blocks)
    
    # Step 3: TSR Table Region Detection
    table_regions = []
    tsr_metadata = {}
    
    if reconstruct_mode == "compare":
        logger.info("Running in compare mode. Executing multiple engines.")
        heuristic_engine = HeuristicTSREngine()
        pp_engine = PPStructure_TSREngine()
        
        heuristic_regions, _ = heuristic_engine.detect_tables(ocr_blocks)
        pp_regions, tsr_metadata = pp_engine.detect_tables(ocr_blocks, image=image)
        
        logger.info(f"[COMPARE] Heuristic detected {len(heuristic_regions)} tables.")
        logger.info(f"[COMPARE] PP-Structure detected {len(pp_regions)} tables.")
        table_regions = pp_regions # Default to ppstructure for rest of pipeline
    else:
        engine = get_engine(reconstruct_mode)
        # Handle heuristic engines that don't need image
        if reconstruct_mode == "heuristic":
            table_regions, tsr_metadata = engine.detect_tables(ocr_blocks)
        else:
            table_regions, tsr_metadata = engine.detect_tables(ocr_blocks, image=image)
    
    # Step 4: Cell Mapping (IoA)
    map_tokens_to_cells(ocr_blocks, table_regions)
    
    # --- Metrics Logging ---
    total_cells = sum(len(r.cells) for r in table_regions)
    total_rows = sum(len(r.rows) for r in table_regions)
    total_cols = sum(len(r.columns) for r in table_regions)
    
    mapped_tokens = set()
    empty_cells = 0
    for r in table_regions:
        for c in r.cells:
            mapped_tokens.update(c.mapped_block_ids)
            if not c.mapped_block_ids:
                empty_cells += 1
            
    orphan_tokens = len(ocr_blocks) - len(mapped_tokens)
    ioa_success_rate = (len(mapped_tokens) / len(ocr_blocks) * 100) if ocr_blocks else 100.0
    empty_cell_ratio = (empty_cells / total_cells * 100) if total_cells else 0.0
    
    logger.info(f"[Metrics] Detected Table Regions: {len(table_regions)}")
    logger.info(f"[Metrics] Total Rows: {total_rows}")
    logger.info(f"[Metrics] Total Columns: {total_cols}")
    logger.info(f"[Metrics] Total Cells: {total_cells}")
    logger.info(f"[Metrics] Orphan Tokens: {orphan_tokens}")
    logger.info(f"[Metrics] Empty Cell Ratio: {empty_cell_ratio:.1f}%")
    logger.info(f"[Metrics] IoA Success Rate: {ioa_success_rate:.1f}%")
    
    # --- Debug Visualization ---
    if debug and ocr_blocks:
        max_x = max([b.original_geometry.max_x for b in ocr_blocks if b.original_geometry] + [1000])
        max_y = max([b.original_geometry.max_y for b in ocr_blocks if b.original_geometry] + [1000])
        draw_debug_visualization(ocr_blocks, table_regions, max_x + 100, max_y + 100, "datasets/debug/latest_reconstruction.png")
    
    # --- Backward Compatibility Layer ---
    legacy_reconstructed_rows = []
    legacy_table_rows = []
    row_counter = 0
    
    for tr in table_regions:
        for row_region in tr.rows:
            # Find cells for this row
            row_cells = [c for c in tr.cells if c.row_id == row_region.row_id]
            
            blocks_in_row = []
            columns_dict = {}
            for cell in row_cells:
                for b_id in cell.mapped_block_ids:
                    orig_b = next((b for b in blocks if b["id"] == b_id), None)
                    if orig_b:
                        blocks_in_row.append(orig_b)
                if cell.text:
                    columns_dict[cell.col_id] = cell.text
                
            legacy_row = {
                "row_index": row_counter,
                "blocks": blocks_in_row,
                "classification": tr.region_type.value,
                "columns": columns_dict
            }
            legacy_reconstructed_rows.append(legacy_row)
            if tr.region_type.value in ["table", "medicine_table"]:
                legacy_table_rows.append(legacy_row)
            row_counter += 1
            
    # Structured Tables Output
    structured_tables = [tr.model_dump(mode='json') for tr in table_regions]
    
    # Generate Semantic Markdown serialization
    from services.semantic_serializer import serialize_to_markdown
    semantic_markdown = serialize_to_markdown(legacy_reconstructed_rows)
    
    return {
        "reconstructed_rows": legacy_reconstructed_rows,
        "detected_table_rows": legacy_table_rows,
        "columns_extracted": True,
        "structured_tables": structured_tables,
        "semantic_markdown": semantic_markdown,
        "metrics": {
            "table_count": len(table_regions),
            "row_count": total_rows,
            "col_count": total_cols,
            "orphan_token_count": orphan_tokens,
            "ioa_success_rate": ioa_success_rate,
            "empty_cell_ratio": empty_cell_ratio,
            **tsr_metadata
        }
    }
