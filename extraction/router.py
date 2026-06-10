import os
from typing import Dict, Type
from extraction.base import DocumentExtractionEngine
from extraction.engines.legacy_engine import LegacyExtractionEngine

# Mapping of supported engine names to their respective engine classes.
ENGINES: Dict[str, Type[DocumentExtractionEngine]] = {
    "legacy": LegacyExtractionEngine,
}

def get_extraction_engine() -> DocumentExtractionEngine:
    """
    Resolves and returns the configured extraction engine instance.
    
    Reads from the EXTRACTION_ENGINE environment variable, defaulting to 'legacy'.
    Raises ValueError for unsupported engine requests.
    """
    engine_name = os.environ.get("EXTRACTION_ENGINE", "legacy").lower().strip()
    if engine_name not in ENGINES:
        raise ValueError(
            f"Unsupported EXTRACTION_ENGINE requested: '{engine_name}'. "
            f"Supported options are: {list(ENGINES.keys())}"
        )
        
    engine_class = ENGINES[engine_name]
    return engine_class()
