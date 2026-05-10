from abc import ABC, abstractmethod
from typing import List
from models.layout_models import OCRBlock, TableRegion

from PIL import Image

from typing import List, Tuple, Dict, Any

class BaseTSREngine(ABC):
    @abstractmethod
    def detect_tables(self, blocks: List[OCRBlock], image: Image.Image = None) -> Tuple[List[TableRegion], Dict[str, Any]]:
        """
        Infers pure structural topology (tables, rows, cols, cells) from OCR blocks.
        Returns tuple of (List of regions, Preprocessing/Execution metadata).
        """
        pass
