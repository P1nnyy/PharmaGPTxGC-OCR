from abc import ABC, abstractmethod
from typing import List
from models.layout_models import OCRBlock, TableRegion

from PIL import Image

class BaseTSREngine(ABC):
    @abstractmethod
    def detect_tables(self, blocks: List[OCRBlock], image: Image.Image = None) -> List[TableRegion]:
        """
        Infers pure structural topology (tables, rows, cols, cells) from OCR blocks.
        Does NOT assign text to cells (that is handled by IoA mapping).
        """
        pass
