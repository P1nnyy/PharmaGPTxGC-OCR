from typing import Any, Dict
from extraction.base import DocumentExtractionEngine

class LegacyExtractionEngine(DocumentExtractionEngine):
    """
    Lazy wrapper for the legacy custom OCR and spatial reconstruction pipeline.
    Does not import heavy pipeline modules at module import time.
    """
    def extract(self, document_path: str, **kwargs) -> Dict[str, Any]:
        """
        Lazily invokes the legacy pipeline.
        Since there is no clean unified library entrypoint on this branch,
        this method raises a NotImplementedError.
        """
        raise NotImplementedError("Legacy extraction engine pipeline execution is not implemented on this branch.")
