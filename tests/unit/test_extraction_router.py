import os
import pytest
from unittest.mock import patch
from extraction.router import get_extraction_engine
from extraction.engines.legacy_engine import LegacyExtractionEngine
from extraction.normalizers.canonical_invoice import CanonicalInvoice, CanonicalLineItem

def test_router_defaults_to_legacy():
    # Ensure EXTRACTION_ENGINE is removed from environment to test default behavior
    with patch.dict(os.environ, {}, clear=True):
        engine = get_extraction_engine()
        assert isinstance(engine, LegacyExtractionEngine)

def test_router_respects_env_var():
    with patch.dict(os.environ, {"EXTRACTION_ENGINE": "legacy"}):
        engine = get_extraction_engine()
        assert isinstance(engine, LegacyExtractionEngine)

def test_router_rejects_unsupported_engine():
    with patch.dict(os.environ, {"EXTRACTION_ENGINE": "unsupported_engine_xyz"}):
        with pytest.raises(ValueError) as excinfo:
            get_extraction_engine()
        assert "Unsupported EXTRACTION_ENGINE requested" in str(excinfo.value)

def test_legacy_engine_exposes_extract():
    engine = LegacyExtractionEngine()
    assert hasattr(engine, "extract")
    assert callable(engine.extract)

def test_canonical_invoice_serialization():
    line_item = CanonicalLineItem(
        name="PARACETAMOL 650 MG",
        pack="10 Tabs",
        batch="B12345",
        expiry="12/28",
        hsn="300490",
        quantity=2,
        free_quantity=0,
        mrp=15.0,
        rate=12.5,
        discount=0.0,
        gst_percent=12.0,
        amount=25.0,
        confidence=0.95
    )
    invoice = CanonicalInvoice(
        invoice_number="INV-001",
        invoice_date="2026-06-11",
        seller_name="Pharma Dist",
        buyer_name="Retail Pharmacy",
        subtotal=25.0,
        discount=0.0,
        cgst=1.5,
        sgst=1.5,
        igst=0.0,
        grand_total=28.0,
        line_items=[line_item],
        confidence=0.9,
        extraction_engine="legacy",
        raw_engine_metadata={"some_raw_key": "some_val"}
    )
    # Pydantic v2 serialization
    dumped = invoice.model_dump()
    assert dumped["invoice_number"] == "INV-001"
    assert dumped["line_items"][0]["name"] == "PARACETAMOL 650 MG"
    assert dumped["line_items"][0]["rate"] == 12.5
    assert dumped["raw_engine_metadata"] == {"some_raw_key": "some_val"}
