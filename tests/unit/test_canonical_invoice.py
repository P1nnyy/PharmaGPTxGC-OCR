from extraction.normalizers.canonical_invoice import CanonicalInvoice, CanonicalLineItem

def test_canonical_invoice_instantiation():
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
    
    assert invoice.invoice_number == "INV-001"
    assert invoice.line_items[0].name == "PARACETAMOL 650 MG"
    
    dumped = invoice.model_dump()
    assert dumped["invoice_number"] == "INV-001"
    assert dumped["line_items"][0]["name"] == "PARACETAMOL 650 MG"
    assert dumped["line_items"][0]["rate"] == 12.5
    assert dumped["raw_engine_metadata"] == {"some_raw_key": "some_val"}
