from abc import ABC, abstractmethod
from typing import Any, Dict

class DocumentExtractionEngine(ABC):
    @abstractmethod
    def extract(self, document_path: str, **kwargs) -> Dict[str, Any]:
        """
        Abstract method to extract data from a document file.
        
        Args:
            document_path: Absolute or relative path to the invoice document image.
            **kwargs: Additional engine-specific execution flags (e.g. reconstruct, extract, bypass_cache, etc.)
            
        Returns:
            A dictionary containing the extraction result (e.g., OCR block primitives, 
            layout tables, clean items, and LLM structured extractions) matching the 
            application's standard output schemas.
        """
        pass
