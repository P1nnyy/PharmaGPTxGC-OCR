"""Tests for the raw Azure Document Intelligence response cache.

These exist because every cache miss is a real, billable Azure call. The
behaviour that matters is: identical bytes must never be analyzed twice, and
normalization must still re-run against the cached response so normalizer
fixes reach already-scanned documents without paying again.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from core.config import settings
from extraction.engines.azure_document_intelligence_engine import AzureDocumentIntelligenceEngine
from extraction.normalizers.canonical_invoice import CanonicalInvoice
from services import cache_service

AZURE_ENV = {
    "DOCUMENTINTELLIGENCE_ENDPOINT": "http://fake-endpoint.com",
    "DOCUMENTINTELLIGENCE_API_KEY": "some-key",
    "AZURE_DI_SAVE_RAW": "false",
}

# A minimal but structurally real Azure response. The point of caching the raw
# payload (rather than the normalized invoice) is that these nested keys
# survive the round trip, so it is asserted on directly below.
RAW_RESPONSE = {
    "modelId": "prebuilt-invoice",
    "tables": [{"rowCount": 2, "columnCount": 3, "cells": [{"rowIndex": 0, "columnIndex": 0, "content": "Item"}]}],
    "documents": [{"fields": {"InvoiceId": {"value": "INV-1"}}}],
    "pages": [{"angle": 0.5, "width": 100, "height": 200}],
}


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Points the cache at a throwaway dir and resets the module-level
    writability flags that would otherwise leak between tests."""
    monkeypatch.setattr(settings, "OCR_RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "ENABLE_CACHE", True)
    monkeypatch.setattr(cache_service, "_CACHE_WRITABLE", None)
    monkeypatch.setattr(cache_service, "_SAVE_DISABLED_FOR_PROCESS", False)
    return tmp_path


@pytest.fixture
def invoice_file(tmp_path):
    path = tmp_path / "invoice.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0 pretend jpeg bytes")
    return str(path)


def _mock_azure_client():
    """Builds a patched DocumentIntelligenceClient returning RAW_RESPONSE."""
    result = MagicMock()
    result.as_dict.return_value = RAW_RESPONSE
    poller = MagicMock()
    poller.result.return_value = result
    instance = MagicMock()
    instance.begin_analyze_document.return_value = poller
    return instance


def _run_extract(invoice_file, client_instance, normalize_mock, bypass_cache=False, env=None):
    with patch.dict(os.environ, {**AZURE_ENV, **(env or {})}), \
         patch("extraction.engines.azure_document_intelligence_engine.load_dotenv"), \
         patch("extraction.engines.azure_document_intelligence_engine.AzureKeyCredential"), \
         patch(
             "extraction.engines.azure_document_intelligence_engine.DocumentIntelligenceClient",
             return_value=client_instance,
         ), \
         patch(
             "extraction.engines.azure_document_intelligence_engine.normalize_azure_invoice",
             normalize_mock,
         ):
        engine = AzureDocumentIntelligenceEngine()
        return engine.extract(invoice_file, bypass_cache=bypass_cache)


def test_first_call_hits_azure_and_stores_raw_response(cache_dir, invoice_file):
    client = _mock_azure_client()
    normalize = MagicMock(return_value=CanonicalInvoice(invoice_number="INV-1"))

    _run_extract(invoice_file, client, normalize)

    assert client.begin_analyze_document.call_count == 1

    stored = list((cache_dir / cache_service.AZURE_RAW_SUBDIR).glob("*.json"))
    assert len(stored) == 1, "raw response should have been cached"

    # The full nested structure must survive - this is exactly what the older
    # _ocr_only_payload path destroyed by flattening to {text, blocks}.
    written = json.loads(stored[0].read_text())
    assert written["tables"][0]["cells"][0]["content"] == "Item"
    assert written["documents"][0]["fields"]["InvoiceId"]["value"] == "INV-1"
    assert written["pages"][0]["angle"] == 0.5


def test_second_identical_call_does_not_hit_azure(cache_dir, invoice_file):
    normalize = MagicMock(return_value=CanonicalInvoice(invoice_number="INV-1"))

    first_client = _mock_azure_client()
    _run_extract(invoice_file, first_client, normalize)
    assert first_client.begin_analyze_document.call_count == 1

    second_client = _mock_azure_client()
    result = _run_extract(invoice_file, second_client, normalize)

    assert second_client.begin_analyze_document.call_count == 0, "cached bytes must not be re-analyzed"
    assert result.invoice_number == "INV-1"


def test_normalizer_reruns_on_cache_hit(cache_dir, invoice_file):
    """The reason for caching the raw response rather than the finished
    invoice: a later normalizer fix must reach already-scanned documents
    without another paid call."""
    first_client = _mock_azure_client()
    _run_extract(invoice_file, first_client, MagicMock(return_value=CanonicalInvoice(invoice_number="OLD")))

    # Simulate a normalizer improvement shipping after the document was scanned.
    improved = MagicMock(return_value=CanonicalInvoice(invoice_number="FIXED"))
    second_client = _mock_azure_client()
    result = _run_extract(invoice_file, second_client, improved)

    assert second_client.begin_analyze_document.call_count == 0
    assert result.invoice_number == "FIXED"
    # And it re-normalized the full cached payload, not a flattened copy.
    improved.assert_called_once()
    assert improved.call_args[0][0]["tables"][0]["rowCount"] == 2


def test_bypass_cache_forces_live_call(cache_dir, invoice_file):
    normalize = MagicMock(return_value=CanonicalInvoice(invoice_number="INV-1"))
    _run_extract(invoice_file, _mock_azure_client(), normalize)

    forced_client = _mock_azure_client()
    _run_extract(invoice_file, forced_client, normalize, bypass_cache=True)

    assert forced_client.begin_analyze_document.call_count == 1


def test_different_model_id_is_a_separate_cache_entry(cache_dir, invoice_file):
    """Same bytes analyzed by a different model produce a different response,
    so a model switch must miss rather than silently reuse."""
    normalize = MagicMock(return_value=CanonicalInvoice(invoice_number="INV-1"))
    _run_extract(invoice_file, _mock_azure_client(), normalize, env={"AZURE_DI_MODEL_ID": "prebuilt-invoice"})

    other_client = _mock_azure_client()
    _run_extract(invoice_file, other_client, normalize, env={"AZURE_DI_MODEL_ID": "custom-trained-v2"})

    assert other_client.begin_analyze_document.call_count == 1
    stored = list((cache_dir / cache_service.AZURE_RAW_SUBDIR).glob("*.json"))
    assert len(stored) == 2


def test_corrupt_cache_entry_falls_back_to_live_call(cache_dir, invoice_file):
    normalize = MagicMock(return_value=CanonicalInvoice(invoice_number="INV-1"))
    _run_extract(invoice_file, _mock_azure_client(), normalize)

    # Truncate the stored entry the way an interrupted write would.
    entry = next((cache_dir / cache_service.AZURE_RAW_SUBDIR).glob("*.json"))
    entry.write_text('{"tables": [')

    recovery_client = _mock_azure_client()
    result = _run_extract(invoice_file, recovery_client, normalize)

    assert recovery_client.begin_analyze_document.call_count == 1, "corrupt entry must not wedge extraction"
    assert result.invoice_number == "INV-1"
    # And the bad entry is replaced by the fresh response.
    assert json.loads(entry.read_text())["modelId"] == "prebuilt-invoice"


def test_caching_disabled_always_calls_azure(cache_dir, invoice_file, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_CACHE", False)
    normalize = MagicMock(return_value=CanonicalInvoice(invoice_number="INV-1"))

    _run_extract(invoice_file, _mock_azure_client(), normalize)
    second_client = _mock_azure_client()
    _run_extract(invoice_file, second_client, normalize)

    assert second_client.begin_analyze_document.call_count == 1


def test_clear_azure_cache_removes_entries(cache_dir, invoice_file):
    normalize = MagicMock(return_value=CanonicalInvoice(invoice_number="INV-1"))
    _run_extract(invoice_file, _mock_azure_client(), normalize)

    assert cache_service.clear_azure_cache() == 1
    assert cache_service.get_cached_azure_response("anything") is None


def test_clear_cache_does_not_drop_paid_azure_responses(cache_dir, invoice_file):
    """clear_cache() is the routine 'Clear Bench' action; it must not silently
    throw away responses that cost money."""
    normalize = MagicMock(return_value=CanonicalInvoice(invoice_number="INV-1"))
    _run_extract(invoice_file, _mock_azure_client(), normalize)

    cache_service.clear_cache()

    remaining = list((cache_dir / cache_service.AZURE_RAW_SUBDIR).glob("*.json"))
    assert len(remaining) == 1
