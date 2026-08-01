import os
import io
import pytest
from unittest.mock import MagicMock, patch, mock_open
from fastapi import UploadFile, HTTPException

from api.routes import upload_invoice
from extraction.normalizers.canonical_invoice import CanonicalInvoice
from services.validators.content_validator import ContentAssessment

# These tests exercise engine routing, not image content, and use a 1x1 GIF as
# a stand-in payload. That is genuinely blank, so the pre-flight content gate
# would (correctly) reject it - stub it out the same way ImageValidator is.
# The gate's own behaviour is covered in test_content_validator.py, and its
# effect on this route in test_content_gate_blocks_azure_call below.
PROCESSABLE = ContentAssessment(is_processable=True)

@pytest.fixture
def clean_env():
    """Fixture to ensure a sanitized env dictionary during testing."""
    with patch.dict(os.environ, {}, clear=True):
        yield

@pytest.mark.anyio
async def test_legacy_route_default(clean_env):
    """Verify that under legacy config, upload_invoice executes the legacy OCR pipeline path."""
    mock_file = MagicMock(spec=UploadFile)
    mock_file.content_type = "image/png"
    mock_file.filename = "test.png"
    mock_file.size = 100
    mock_file.read.return_value = b"GIF89a\x01\x00\x01\x00\x80\xff\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    
    mock_ocr = {"text": "legacy text", "blocks": []}
    
    # Mock legacy OCR process call and caching to avoid physical resource loading
    with patch.dict(os.environ, {"EXTRACTION_ENGINE": "legacy"}), \
         patch("api.routes.ocr_engine.process_image", return_value=mock_ocr) as mock_process, \
         patch("api.routes.cache_service.get_cached_result", return_value=None), \
         patch("api.routes.cache_service.save_result"), \
         patch("api.routes.content_validator.assess", return_value=PROCESSABLE), \
         patch("services.validators.image_validator.ImageValidator.validate_image", return_value={
             "is_valid": True,
             "quality_score": 1.0,
             "properties": {"mode": "RGB"},
             "warnings": [],
             "errors": []
         }):
         
        response = await upload_invoice(file=mock_file)
        
        assert response.cached is False
        assert response.text == "legacy text"
        mock_process.assert_called_once()

@pytest.mark.anyio
async def test_azure_route_path(clean_env):
    """Verify that under azure config, upload_invoice invokes AzureDocumentIntelligenceEngine."""
    mock_file = MagicMock(spec=UploadFile)
    mock_file.content_type = "image/png"
    mock_file.filename = "test.png"
    mock_file.size = 100
    mock_file.read.return_value = b"GIF89a\x01\x00\x01\x00\x80\xff\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    
    mock_invoice = CanonicalInvoice(
        invoice_number="INV-AZURE-789",
        seller_name="Apothecary Agencies",
        buyer_name="Deepak Retail",
        subtotal=2320.90,
        grand_total=2291.00
    )
    
    # Mock AzureDocumentIntelligenceEngine extraction method and load_dotenv
    with patch.dict(os.environ, {"EXTRACTION_ENGINE": "azure"}), \
         patch("extraction.engines.azure_document_intelligence_engine.load_dotenv"), \
         patch("extraction.engines.azure_document_intelligence_engine.AzureDocumentIntelligenceEngine.extract", return_value=mock_invoice) as mock_extract, \
         patch("api.routes.content_validator.assess", return_value=PROCESSABLE), \
         patch("services.validators.image_validator.ImageValidator.validate_image", return_value={
             "is_valid": True,
             "properties": {}
         }), \
         patch("builtins.open", mock_open()):
         
        response = await upload_invoice(file=mock_file)
        
        assert response["invoice_number"] == "INV-AZURE-789"
        assert response["seller_name"] == "Apothecary Agencies"
        assert response["buyer_name"] == "Deepak Retail"
        assert response["subtotal"] == 2320.90
        assert response["grand_total"] == 2291.00
        
        # Assert extraction method was triggered
        mock_extract.assert_called_once()


@pytest.mark.anyio
async def test_content_gate_blocks_azure_call(clean_env):
    """The gate's whole purpose: a structurally empty upload must be rejected
    with a 400 and must never reach the (billable) extraction engine."""
    mock_file = MagicMock(spec=UploadFile)
    mock_file.content_type = "image/png"
    mock_file.filename = "blank.png"
    mock_file.size = 100
    mock_file.read.return_value = b"GIF89a\x01\x00\x01\x00\x80\xff\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"

    with patch.dict(os.environ, {"EXTRACTION_ENGINE": "azure"}), \
         patch("extraction.engines.azure_document_intelligence_engine.load_dotenv"), \
         patch(
             "extraction.engines.azure_document_intelligence_engine.AzureDocumentIntelligenceEngine.extract"
         ) as mock_extract, \
         patch("services.validators.image_validator.ImageValidator.validate_image", return_value={
             "is_valid": True,
             "properties": {}
         }):

        with pytest.raises(HTTPException) as excinfo:
            await upload_invoice(file=mock_file)

        assert excinfo.value.status_code == 400
        # a blank upload must not reach the paid extractor
        mock_extract.assert_not_called()


@pytest.mark.anyio
async def test_content_gate_can_be_disabled(clean_env):
    """Escape hatch: with the gate off, the same payload reaches the engine."""
    mock_file = MagicMock(spec=UploadFile)
    mock_file.content_type = "image/png"
    mock_file.filename = "blank.png"
    mock_file.size = 100
    mock_file.read.return_value = b"GIF89a\x01\x00\x01\x00\x80\xff\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"

    with patch.dict(os.environ, {"EXTRACTION_ENGINE": "azure"}), \
         patch("api.routes.settings.CONTENT_GATE_ENABLED", False), \
         patch("extraction.engines.azure_document_intelligence_engine.load_dotenv"), \
         patch(
             "extraction.engines.azure_document_intelligence_engine.AzureDocumentIntelligenceEngine.extract",
             return_value=CanonicalInvoice(invoice_number="INV-1"),
         ) as mock_extract, \
         patch("services.validators.image_validator.ImageValidator.validate_image", return_value={
             "is_valid": True,
             "properties": {}
         }), \
         patch("builtins.open", mock_open()):

        await upload_invoice(file=mock_file)
        mock_extract.assert_called_once()
