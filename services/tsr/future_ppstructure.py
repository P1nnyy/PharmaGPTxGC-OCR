from typing import List
from models.layout_models import OCRBlock, TableRegion
from services.tsr.base_tsr import BaseTSREngine

class PPStructure_TSREngine(BaseTSREngine):
    def detect_tables(self, blocks: List[OCRBlock]) -> List[TableRegion]:
        # TODO: Implement PaddleOCR PP-Structure inference
        return []
