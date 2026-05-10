from typing import List, Tuple, Dict, Any
from models.layout_models import OCRBlock, TableRegion
from services.tsr.base_tsr import BaseTSREngine
from PIL import Image

class TATR_TSREngine(BaseTSREngine):
    def detect_tables(self, blocks: List[OCRBlock], image: Image.Image = None) -> Tuple[List[TableRegion], Dict[str, Any]]:
        # TODO: Implement Microsoft Table Transformer (TATR) inference
        return [], {}
