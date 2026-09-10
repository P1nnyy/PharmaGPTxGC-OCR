"""Turning stored sales into outward documents.

The mapping is pure given a row, so it is tested directly rather than through
a database. What is actually under test is the one judgement the repository
makes: filling in the place of supply for a sale made across the counter.

That is not a guess. A supply of goods the customer carries away is supplied
where they collect it, so a counter bill is intra-state however far the
customer travelled. A photographed or imported bill gets no such treatment -
those can be deliveries, and a delivery is supplied where it is sent.
"""

from decimal import Decimal

from db.repositories.gstr1_repository import _document, _line
from services.gstr1.model import DocumentStatus, SupplyClass, SupplyType

OWN_STATE = "27"


def row(**sale):
    base = {
        "id": "S1",
        "sale_date": "2026-09-05",
        "tax_period": "092026",
        "capture_mode": "COUNTER",
        "status": "CONFIRMED",
    }
    base.update(sale)
    return {"sale": base, "lines": [], "rate_blocks": []}


class TestPlaceOfSupply:
    def test_a_counter_bill_with_none_recorded_is_supplied_at_the_shop(self):
        document = _document(row(capture_mode="COUNTER"), OWN_STATE)
        assert document.place_of_supply_state_code == OWN_STATE
        assert document.supply_type == SupplyType.INTRA

    def test_a_day_total_is_supplied_at_the_shop_too(self):
        document = _document(row(capture_mode="DAY_TOTAL", is_aggregate=True), OWN_STATE)
        assert document.place_of_supply_state_code == OWN_STATE

    def test_a_photographed_bill_is_left_empty(self):
        # It might be a delivery. Guessing here would file an inter-state
        # supply as CGST plus SGST.
        document = _document(row(capture_mode="BILL_PHOTO"), OWN_STATE)
        assert document.place_of_supply_state_code is None
        assert document.supply_type is None

    def test_an_imported_row_is_left_empty(self):
        document = _document(row(capture_mode="IMPORT"), OWN_STATE)
        assert document.place_of_supply_state_code is None

    def test_a_recorded_place_of_supply_is_never_overwritten(self):
        # Even on a counter bill: if somebody recorded 29, that is the answer.
        document = _document(
            row(capture_mode="COUNTER", place_of_supply_state_code="29"), OWN_STATE
        )
        assert document.place_of_supply_state_code == "29"
        assert document.supply_type == SupplyType.INTER


class TestDefaults:
    def test_paise_that_were_never_written_read_as_zero(self):
        document = _document(row(), OWN_STATE)
        assert document.taxable_paise == 0
        assert document.igst_paise == 0
        assert document.cess_paise == 0

    def test_a_sale_with_no_document_type_is_an_invoice(self):
        assert _document(row(), OWN_STATE).sign == 1

    def test_a_credit_note_subtracts(self):
        assert _document(row(document_type="CREDIT_NOTE"), OWN_STATE).sign == -1

    def test_an_unrecognised_status_is_treated_as_a_draft(self):
        # Excluded from every table rather than silently reported. A status
        # nobody defined is not evidence that a person confirmed the figures.
        document = _document(row(status="SOMETHING_ELSE"), OWN_STATE)
        assert document.status == DocumentStatus.DRAFT
        assert not document.is_reportable

    def test_the_counter_serial_stands_in_for_a_bill_number(self):
        # A1 writes the counter's serial to `serial`; everything else uses
        # `bill_number`.
        assert _document(row(serial="CTR-000004"), OWN_STATE).bill_number == "CTR-000004"


class TestLines:
    def test_maps_what_the_pack_says_onto_the_portals_unit(self):
        line = _line({"uqc": "strip", "quantity": 2, "hsn": "3004"})
        assert line.uqc == "TBS"

    def test_an_unmappable_unit_becomes_none_rather_than_others(self):
        assert _line({"uqc": "banana"}).uqc is None

    def test_quantity_is_exact(self):
        assert _line({"quantity": 0.1}).quantity == Decimal("0.1")

    def test_an_unrecognised_supply_class_falls_back_to_taxable(self):
        assert _line({"supply_class": "NONSENSE"}).supply_class == SupplyClass.TAXABLE

    def test_carries_the_supply_class_that_was_stored(self):
        assert _line({"supply_class": "NIL_RATED"}).supply_class == SupplyClass.NIL_RATED
