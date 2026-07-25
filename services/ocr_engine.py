import io
import os
from typing import Dict, Any, List
from PIL import Image

from core.config import settings
from core.logger import logger

try:
    from azure.ai.formrecognizer import DocumentAnalysisClient
    from azure.core.credentials import AzureKeyCredential
except ImportError:
    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient as DocumentAnalysisClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError:
        DocumentAnalysisClient = None
        AzureKeyCredential = None


def process_image(image: Image.Image, langs: List[str] = ["en"]) -> Dict[str, Any]:
    """
    Processes an invoice image via Azure Document Intelligence (prebuilt-layout model).
    Converts PIL image to bytes, calls Azure Document Analysis, and structures
    extracted text, bounding polygons (blocks), and table cell grids.
    """
    endpoint = settings.AZURE_DOCUMENT_ENDPOINT or os.environ.get("AZURE_DOCUMENT_ENDPOINT") or os.environ.get("DOCUMENTINTELLIGENCE_ENDPOINT", "")
    key = settings.AZURE_DOCUMENT_KEY or os.environ.get("AZURE_DOCUMENT_KEY") or os.environ.get("DOCUMENTINTELLIGENCE_API_KEY", "")

    if not endpoint or not key:
        logger.warning("Azure Document Intelligence credentials missing in settings/env.")
        return {
            "text": "",
            "blocks": [],
            "tables": [],
            "error": "Azure credentials not configured."
        }

    # Convert PIL Image to byte stream
    img_byte_arr = io.BytesIO()
    img_format = image.format if image.format else "JPEG"
    image.save(img_byte_arr, format=img_format)
    img_bytes = img_byte_arr.getvalue()

    client = DocumentAnalysisClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key)
    )

    logger.info("Submitting document to Azure Document Intelligence prebuilt-layout model...")
    poller = client.begin_analyze_document("prebuilt-layout", document=img_bytes)
    result = poller.result()

    full_text = getattr(result, "content", "") or ""
    blocks: List[Dict[str, Any]] = []

    # Map pages and lines into standard block structures
    pages = getattr(result, "pages", []) or []
    for page in pages:
        lines = getattr(page, "lines", []) or []
        for line in lines:
            line_text = getattr(line, "content", "")
            polygon_obj = getattr(line, "polygon", None)
            polygon = []
            if polygon_obj:
                if isinstance(polygon_obj, (list, tuple)):
                    if len(polygon_obj) > 0 and hasattr(polygon_obj[0], "x"):
                        polygon = [[pt.x, pt.y] for pt in polygon_obj]
                    elif len(polygon_obj) >= 4 and isinstance(polygon_obj[0], (int, float)):
                        # Pairs of (x, y)
                        polygon = [[polygon_obj[i], polygon_obj[i+1]] for i in range(0, len(polygon_obj), 2)]
                    else:
                        polygon = polygon_obj
                else:
                    polygon = polygon_obj

            blocks.append({
                "text": line_text,
                "polygon": polygon,
                "confidence": getattr(line, "confidence", 1.0)
            })

    # Map tables array
    raw_tables = getattr(result, "tables", []) or []
    tables: List[Dict[str, Any]] = []

    for t_idx, table in enumerate(raw_tables):
        row_count = getattr(table, "row_count", 0)
        column_count = getattr(table, "column_count", 0)
        raw_cells = getattr(table, "cells", []) or []

        cells: List[Dict[str, Any]] = []
        for cell in raw_cells:
            cell_poly = getattr(cell, "bounding_regions", None)
            cell_polygon = []
            if cell_poly and len(cell_poly) > 0:
                poly = getattr(cell_poly[0], "polygon", None)
                if poly:
                    cell_polygon = [[pt.x, pt.y] for pt in poly] if hasattr(poly[0], "x") else poly

            cells.append({
                "row_index": getattr(cell, "row_index", 0),
                "column_index": getattr(cell, "column_index", 0),
                "row_span": getattr(cell, "row_span", 1),
                "column_span": getattr(cell, "column_span", 1),
                "text": getattr(cell, "content", ""),
                "kind": getattr(cell, "kind", "content"),
                "polygon": cell_polygon
            })

        tables.append({
            "table_id": f"table_{t_idx}",
            "row_count": row_count,
            "column_count": column_count,
            "cells": cells
        })

    return {
        "text": full_text,
        "blocks": blocks,
        "tables": tables
    }
