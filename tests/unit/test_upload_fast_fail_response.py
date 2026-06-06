from api.routes import _apply_no_valid_table_response_defaults
from models.schemas import OCRResponse
from services.llm_extractor import InvoiceSchema


def test_no_valid_table_candidate_response_defaults_validate_without_invoice_schema_tax_error():
    metadata = {
        "fast_fail": True,
        "fast_fail_reason": "no_valid_table_candidate",
        "selected_table_available": False,
        "semantic_markdown": "",
        "metrics": {
            "selected_table_available": False,
            "no_valid_table_candidate": True,
        },
    }

    normalized = _apply_no_valid_table_response_defaults(
        metadata,
        invoice_id="invoice_123",
        filename="mahajan.png",
    )

    response = OCRResponse(
        invoice_id="invoice_123",
        cached=False,
        text="",
        metadata=normalized,
    )
    llm_payload = InvoiceSchema(**normalized["llm_extraction"]).model_dump()

    assert response.metadata.fast_fail_reason == "no_valid_table_candidate"
    assert response.metadata.selected_table_available is False
    assert response.metadata.safe_for_erp is False
    assert "no_valid_table_candidate" in response.metadata.quality_gate["reasons"]
    assert llm_payload["items"] == []
    assert llm_payload["tax"]["cgst"] == 0.0
    assert llm_payload["tax"]["total_tax"] == 0.0
