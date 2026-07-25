import os
import pytest
from unittest.mock import patch
from extraction.router import get_extraction_engine
from extraction.engines.legacy_engine import LegacyExtractionEngine
from extraction.engines.azure_document_intelligence_engine import AzureDocumentIntelligenceEngine

def test_router_defaults_to_azure():
    with patch.dict(os.environ, {}, clear=True):
        engine = get_extraction_engine()
        assert isinstance(engine, AzureDocumentIntelligenceEngine)

def test_router_respects_env_var():
    with patch.dict(os.environ, {"EXTRACTION_ENGINE": "legacy"}):
        engine = get_extraction_engine()
        assert isinstance(engine, LegacyExtractionEngine)

def test_router_routes_to_azure():
    with patch.dict(os.environ, {"EXTRACTION_ENGINE": "azure"}):
        engine = get_extraction_engine()
        assert isinstance(engine, AzureDocumentIntelligenceEngine)

def test_router_rejects_unsupported_engine():
    with patch.dict(os.environ, {"EXTRACTION_ENGINE": "unsupported_engine_xyz"}):
        with pytest.raises(ValueError) as excinfo:
            get_extraction_engine()
        assert "Unsupported EXTRACTION_ENGINE requested" in str(excinfo.value)

def test_legacy_engine_can_be_instantiated():
    engine = LegacyExtractionEngine()
    assert isinstance(engine, LegacyExtractionEngine)

def test_azure_engine_can_be_instantiated():
    # Verify that AzureDocumentIntelligenceEngine compiles and can be instantiated
    engine = AzureDocumentIntelligenceEngine()
    assert isinstance(engine, AzureDocumentIntelligenceEngine)

