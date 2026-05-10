import numpy as np
from PIL import Image
from typing import List
from models.layout_models import OCRBlock, TableRegion, RowRegion, ColumnRegion, TableCell, GeometryBox, RegionType
from services.tsr.base_tsr import BaseTSREngine
from core.logger import logger

class PPStructure_TSREngine(BaseTSREngine):
    def __init__(self):
        self._engine = None
        
    def _get_engine(self):
        if self._engine is None:
            logger.info("Lazy loading PP-StructureV3...")
            from paddleocr import PPStructure
            # show_log=False prevents paddleocr from spamming the console
            self._engine = PPStructure(show_log=False, image_orientation=False)
        return self._engine

    def detect_tables(self, blocks: List[OCRBlock], image: Image.Image = None) -> List[TableRegion]:
        if image is None:
            logger.warning("PPStructure requires an image, but None was provided. Returning empty list.")
            return []
            
        engine = self._get_engine()
        
        # Convert PIL Image to BGR OpenCV format for PaddleOCR
        img_np = np.array(image.convert("RGB"))
        img_cv = img_np[:, :, ::-1] # RGB to BGR
        
        logger.info("Running PP-Structure inference...")
        results = engine(img_cv)
        
        table_regions = []
        table_counter = 0
        
        for res in results:
            if res.get('type') == 'table':
                bbox = res.get('bbox') # [x1, y1, x2, y2]
                res_data = res.get('res', {})
                html = res_data.get('html', '')
                cell_bboxes = res_data.get('cell_bbox', []) # list of [x1, y1, x2, y2]
                
                table_geom = GeometryBox(
                    min_x=bbox[0], min_y=bbox[1],
                    max_x=bbox[2], max_y=bbox[3],
                    center_x=(bbox[0] + bbox[2]) / 2,
                    center_y=(bbox[1] + bbox[3]) / 2
                )
                
                region = TableRegion(
                    table_id=f"table_{table_counter}",
                    region_type=RegionType.TABLE, # Let downstream tasks classify if it's medicine or total
                    geometry=table_geom,
                    source_engine="ppstructure"
                )
                
                # PP-Structure returns cells in a flattened left-to-right, top-to-bottom order.
                # However, it doesn't give us explicit row/col indices directly without parsing the HTML.
                # Since we have the cell bounding boxes, we can geometrically infer rows and columns.
                
                # For simplicity and robustness, we can extract row/col grid from the cell_bboxes y and x coords.
                # Or we can just use the HTML. Let's use geometry clustering on cell_bboxes.
                
                y_centers = [(b[1] + b[3]) / 2 for b in cell_bboxes]
                y_sorted = sorted(list(set(y_centers)))
                # Cluster y_centers to find rows
                row_clusters = []
                for y in y_sorted:
                    if not row_clusters or y - row_clusters[-1][-1] > 10:
                        row_clusters.append([y])
                    else:
                        row_clusters[-1].append(y)
                row_y_centers = [sum(c)/len(c) for c in row_clusters]
                
                x_centers = [(b[0] + b[2]) / 2 for b in cell_bboxes]
                x_sorted = sorted(list(set(x_centers)))
                # Cluster x_centers to find cols
                col_clusters = []
                for x in x_sorted:
                    if not col_clusters or x - col_clusters[-1][-1] > 10:
                        col_clusters.append([x])
                    else:
                        col_clusters[-1].append(x)
                col_x_centers = [sum(c)/len(c) for c in col_clusters]
                
                # Create Row and Col Regions conceptually
                for i, ry in enumerate(row_y_centers):
                    region.rows.append(RowRegion(row_id=f"row_{i}"))
                for j, cx in enumerate(col_x_centers):
                    region.columns.append(ColumnRegion(col_id=f"col_{j}"))
                
                # Assign cells
                for cell_box in cell_bboxes:
                    cy = (cell_box[1] + cell_box[3]) / 2
                    cx = (cell_box[0] + cell_box[2]) / 2
                    
                    # Find closest row and col
                    row_idx = min(range(len(row_y_centers)), key=lambda i: abs(row_y_centers[i] - cy))
                    col_idx = min(range(len(col_x_centers)), key=lambda j: abs(col_x_centers[j] - cx))
                    
                    cell_geom = GeometryBox(
                        min_x=cell_box[0], min_y=cell_box[1],
                        max_x=cell_box[2], max_y=cell_box[3],
                        center_x=cx, center_y=cy
                    )
                    
                    region.cells.append(TableCell(
                        row_id=f"row_{row_idx}",
                        col_id=f"col_{col_idx}",
                        geometry=cell_geom
                    ))
                
                table_regions.append(region)
                table_counter += 1
                
        return table_regions
