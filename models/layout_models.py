from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field

class RegionType(str, Enum):
    TABLE = "table"
    METADATA = "metadata"
    TOTALS = "totals"
    FOOTER = "footer"
    HEADER = "header"
    MEDICINE_TABLE = "medicine_table"
    UNKNOWN = "unknown"

class GeometryBox(BaseModel):
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    center_x: float
    center_y: float

class OCRBlock(BaseModel):
    id: Optional[str] = None
    text: str = ""
    polygon: List[Tuple[float, float]] = Field(default_factory=list)
    original_geometry: Optional[GeometryBox] = None
    normalized_geometry: Optional[GeometryBox] = None
    
    # Numeric tokens often align to the right edge
    @property
    def right_edge(self) -> float:
        if self.normalized_geometry:
            return self.normalized_geometry.max_x
        return 0.0

    @property
    def is_numeric(self) -> bool:
        """Heuristic to check if token is numeric-like (price, quantity, GST)."""
        import re
        # matches 12.34, 1,234.00, etc.
        return bool(re.search(r'^\s*[\d,]+\.\d{2}\s*$', self.text)) or bool(re.search(r'^\s*\d+\s*$', self.text))

class ColumnAssignment(BaseModel):
    col_id: str
    text: str

class ReconstructedRow(BaseModel):
    row_index: int = -1
    blocks: List[OCRBlock] = Field(default_factory=list)
    classification: str = "Unknown"
    columns: Dict[str, str] = Field(default_factory=dict)

class RowRegion(BaseModel):
    row_id: str
    geometry: Optional[GeometryBox] = None
    confidence: float = 1.0

class ColumnRegion(BaseModel):
    col_id: str
    geometry: Optional[GeometryBox] = None
    confidence: float = 1.0

class TableCell(BaseModel):
    row_id: str
    col_id: str
    geometry: Optional[GeometryBox] = None
    rowspan: int = 1
    colspan: int = 1
    confidence: float = 1.0
    mapped_block_ids: List[str] = Field(default_factory=list)
    text: str = ""

class TableRegion(BaseModel):
    table_id: str
    region_type: RegionType = RegionType.UNKNOWN
    geometry: Optional[GeometryBox] = None
    rows: List[RowRegion] = Field(default_factory=list)
    columns: List[ColumnRegion] = Field(default_factory=list)
    cells: List[TableCell] = Field(default_factory=list)
    confidence: float = 1.0
    source_engine: str = "unknown"
