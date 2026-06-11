import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from extraction.engines.azure_document_intelligence_engine import AzureDocumentIntelligenceEngine
from extraction.normalizers.canonical_invoice import CanonicalInvoice

@pytest.fixture
def clean_env():
    """Fixture to ensure a sanitized env dictionary during testing."""
    with patch.dict(os.environ, {}, clear=True):
        yield

def test_missing_endpoint_raises_value_error(clean_env):
    """Verify ValueError is raised if endpoint env var is missing."""
    with patch.dict(os.environ, {"DOCUMENTINTELLIGENCE_API_KEY": "some-key"}):
        engine = AzureDocumentIntelligenceEngine()
        with pytest.raises(ValueError) as excinfo:
            engine.extract("fake/path.jpg")
        assert "DOCUMENTINTELLIGENCE_ENDPOINT is not configured" in str(excinfo.value)

def test_missing_api_key_raises_value_error(clean_env):
    """Verify ValueError is raised if API key env var is missing."""
    with patch.dict(os.environ, {"DOCUMENTINTELLIGENCE_ENDPOINT": "http://fake-endpoint.com"}):
        engine = AzureDocumentIntelligenceEngine()
        with pytest.raises(ValueError) as excinfo:
            engine.extract("fake/path.jpg")
        assert "DOCUMENTINTELLIGENCE_API_KEY is not configured" in str(excinfo.value)

def test_missing_file_raises_file_not_found(clean_env):
    """Verify FileNotFoundError is raised if the target document does not exist."""
    env_vars = {
        "DOCUMENTINTELLIGENCE_ENDPOINT": "http://fake-endpoint.com",
        "DOCUMENTINTELLIGENCE_API_KEY": "some-key"
    }
    with patch.dict(os.environ, env_vars):
        engine = AzureDocumentIntelligenceEngine()
        with pytest.raises(FileNotFoundError) as excinfo:
            engine.extract("fake/non_existent_file.jpg")
        assert "Document file not found at" in str(excinfo.value)

@patch("extraction.engines.azure_document_intelligence_engine.DocumentIntelligenceClient")
@patch("extraction.engines.azure_document_intelligence_engine.AzureKeyCredential")
@patch("extraction.engines.azure_document_intelligence_engine.normalize_azure_invoice")
@patch("builtins.open", new_callable=mock_open)
@patch("pathlib.Path.exists")
def test_successful_extract(mock_exists, mock_file, mock_normalize, mock_credential, mock_client, clean_env):
    """Verify successful extraction, credentials binding, and result parsing."""
    mock_exists.return_value = True
    
    # Mock Azure client poller and result objects
    mock_result = MagicMock()
    mock_dict = {"tables": [], "documents": []}
    mock_result.as_dict.return_value = mock_dict
    
    mock_poller = MagicMock()
    mock_poller.result.return_value = mock_result
    
    mock_client_instance = MagicMock()
    mock_client_instance.begin_analyze_document.return_value = mock_poller
    mock_client.return_value = mock_client_instance
    
    # Mock normalizer output
    mock_invoice = CanonicalInvoice(invoice_number="INV-MOCK")
    mock_normalize.return_value = mock_invoice
    
    env_vars = {
        "DOCUMENTINTELLIGENCE_ENDPOINT": "http://fake-endpoint.com",
        "DOCUMENTINTELLIGENCE_API_KEY": "some-key",
        "AZURE_DI_MODEL_ID": "custom-model",
        "AZURE_DI_SAVE_RAW": "false"
    }
    
    with patch.dict(os.environ, env_vars):
        engine = AzureDocumentIntelligenceEngine()
        invoice = engine.extract("fake/path.jpg")
        
        # Assert configured properties
        assert engine.model_id == "custom-model"
        assert engine.save_raw is False
        assert invoice == mock_invoice
        
        # Verify Azure Client invocation
        mock_client.assert_called_once_with(
            endpoint="http://fake-endpoint.com",
            credential=mock_credential("some-key")
        )
        mock_client_instance.begin_analyze_document.assert_called_once()
        mock_normalize.assert_called_once_with(mock_dict)

@patch("extraction.engines.azure_document_intelligence_engine.DocumentIntelligenceClient")
@patch("extraction.engines.azure_document_intelligence_engine.AzureKeyCredential")
@patch("extraction.engines.azure_document_intelligence_engine.normalize_azure_invoice")
@patch("pathlib.Path.exists")
def test_extract_saves_raw_when_configured(mock_exists, mock_normalize, mock_credential, mock_client, clean_env):
    """Verify raw JSON responses are saved to local_runs when configured to do so."""
    mock_exists.return_value = True
    
    # Mock Azure client poller and dict output
    mock_result = MagicMock()
    mock_dict = {"tables": [], "documents": [], "test_raw_key": "some_value"}
    mock_result.as_dict.return_value = mock_dict
    
    mock_poller = MagicMock()
    mock_poller.result.return_value = mock_result
    
    mock_client_instance = MagicMock()
    mock_client_instance.begin_analyze_document.return_value = mock_poller
    mock_client.return_value = mock_client_instance
    
    mock_invoice = CanonicalInvoice(invoice_number="INV-MOCK")
    mock_normalize.return_value = mock_invoice
    
    env_vars = {
        "DOCUMENTINTELLIGENCE_ENDPOINT": "http://fake-endpoint.com",
        "DOCUMENTINTELLIGENCE_API_KEY": "some-key",
        "AZURE_DI_SAVE_RAW": "true"
    }
    
    with patch.dict(os.environ, env_vars):
        engine = AzureDocumentIntelligenceEngine()
        
        # Custom mock for builtins.open to intercept the write stream without executing disk I/O
        written_data = []
        def mock_open_write(file, mode, *args, **kwargs):
            if "w" in mode:
                file_mock = MagicMock()
                file_mock.write = lambda s: written_data.append(s)
                file_mock.__enter__.return_value = file_mock
                return file_mock
            file_mock = MagicMock()
            file_mock.__enter__.return_value = file_mock
            return file_mock

        with patch("builtins.open", side_effect=mock_open_write), \
             patch("pathlib.Path.mkdir") as mock_mkdir:
             
            invoice = engine.extract("fake/path.jpg")
            
            # Assert raw logs side effects
            assert engine.save_raw is True
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
            
            # Reconstruct and parse written output
            combined_json = "".join(written_data)
            parsed_written = json.loads(combined_json)
            assert parsed_written["test_raw_key"] == "some_value"
