import os
from typing import Dict, Type
from extraction.base import DocumentExtractionEngine
from extraction.engines.legacy_engine import LegacyExtractionEngine
from extraction.engines.azure_document_intelligence_engine import AzureDocumentIntelligenceEngine

# Mapping of supported engine names to their respective engine classes.
# Supports 'legacy' (original OCR/TSR) and 'azure' (Document Intelligence).
ENGINES: Dict[str, Type[DocumentExtractionEngine]] = {
    "legacy": LegacyExtractionEngine,
    "azure": AzureDocumentIntelligenceEngine,
    "azure_shadow": AzureDocumentIntelligenceEngine,
}

def get_extraction_engine() -> DocumentExtractionEngine:
    """
    Resolves and returns the configured extraction engine instance.
    
    Reads from the EXTRACTION_ENGINE environment variable, defaulting to 'azure'.
    Raises ValueError for unsupported engine requests.
    """
    engine_name = os.environ.get("EXTRACTION_ENGINE", "azure").lower().strip()
    if engine_name not in ENGINES:
        raise ValueError(
            f"Unsupported EXTRACTION_ENGINE requested: '{engine_name}'. "
            f"Supported options are: {list(ENGINES.keys())}"
        )
        
    engine_class = ENGINES[engine_name]
    return engine_class()

