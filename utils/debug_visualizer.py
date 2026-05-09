import os
from PIL import Image, ImageDraw, ImageFont
from typing import List, Dict, Any
from core.logger import logger

def draw_debug_visualization(blocks: List[Dict[str, Any]], rows: List[Dict[str, Any]], image_width: int, image_height: int, output_path: str):
    """
    Renders a debug image visualizing the spatial reconstruction.
    """
    try:
        # Create a blank white image if we don't have the original
        img = Image.new('RGB', (int(image_width), int(image_height)), color='white')
        draw = ImageDraw.Draw(img)
        
        # Define colors
        COLOR_RAW_POLYGON = (200, 200, 200)      # Light gray
        COLOR_NORMALIZED_BBOX = (150, 150, 255)  # Light blue
        
        # Color mapping for row classification
        CLASS_COLORS = {
            "Header": (100, 100, 100),           # Dark gray
            "Medicine Table Row": (0, 200, 0),   # Green
            "Totals": (200, 100, 0),             # Orange
            "Footer": (100, 100, 100),           # Dark gray
            "Unknown": (255, 100, 100)           # Light red
        }
        
        # 1. Draw raw polygons
        for block in blocks:
            poly = block.get("polygon", [])
            if len(poly) == 4:
                pts = [(p[0], p[1]) for p in poly]
                pts.append(pts[0]) # close loop
                draw.line(pts, fill=COLOR_RAW_POLYGON, width=1)
                
        # 2. Draw Rows and Classifications
        for row in rows:
            cls = row.get("classification", "Unknown")
            color = CLASS_COLORS.get(cls, CLASS_COLORS["Unknown"])
            
            # Find row bounding box
            r_min_x = min(b["normalized_geometry"]["min_x"] for b in row["blocks"])
            r_max_x = max(b["normalized_geometry"]["max_x"] for b in row["blocks"])
            r_min_y = min(b["normalized_geometry"]["min_y"] for b in row["blocks"])
            r_max_y = max(b["normalized_geometry"]["max_y"] for b in row["blocks"])
            
            # Draw row bounding box
            draw.rectangle([r_min_x, r_min_y, r_max_x, r_max_y], outline=color, width=2)
            
            # Draw row class text
            draw.text((r_min_x, max(0, r_min_y - 15)), f"{cls} (Row {row.get('row_index')})", fill=color)
            
            # Draw normalized blocks inside the row
            for b in row["blocks"]:
                geom = b["normalized_geometry"]
                draw.rectangle([geom["min_x"], geom["min_y"], geom["max_x"], geom["max_y"]], outline=COLOR_NORMALIZED_BBOX, width=1)
                draw.text((geom["min_x"] + 2, geom["min_y"] + 2), b.get("text", "")[:10], fill=(0,0,0))
                
        # Save output
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path)
        logger.info(f"Debug visualization saved to {output_path}")
        
    except Exception as e:
        logger.error(f"Failed to generate debug visualization: {e}")
