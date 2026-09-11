"""Recording a bill that was issued offline.

Two properties are load-bearing and everything else here is detail.

**The key is (series, number, financial year).** Serial blocks are disjoint per
device, so two bills can never claim one number, and a replayed POST lands on
the record that already exists. That is why sync needs no ordering and no
conflict resolver — not because conflicts are handled, but because they cannot
be constructed.

**The bill survives.** It was printed and handed to a customer before this
request was made. Nothing the server finds can un-issue it, so every check that
fails produces a reconciliation task rather than a rejection.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException, Response

from api.routers.sales import CounterSaleRequest, SaleLineIn, record_counter_sale
from core.idempotency import dedupe_key
from core.tenancy import tenant_scope

USER = {"id": "u-1", "email": "o@example.com", "name": "Owner",
        "role": "super_admin", "pharmacy_id": "ph-1", "is_active": True}


@pytest.fixture(autouse=True)
def workspace():
    with tenant_scope("ph-1"):
        yield


@pytest.fixture(autouse=True)
def no_audit():
    with patch("api.routers.sales.audit_repository.record"):
        yield


def a_bill(**overrides) -> CounterSaleRequest:
    payload = {
        "serial": "CTR-000042",
        "sale_date": "2026-09-10",
        "issued_at": "2026-09-10T11:00:00Z",
        "device_id": "counter-1",
        "lines": [SaleLineIn(line_id="l1", product_id="p1", product_name="CALPOL", quantity=2)],
        "totals": {"taxable_paise": 10000, "cgst_paise": 600, "sgst_paise": 600,
                   "exempt_paise": 0, "nil_rated_paise": 0, "non_gst_paise": 0,
                   "round_off_paise": 0, "grand_total_paise": 11200, "rate_blocks": []},
        "payments": [{"method": "cash", "amount_paise": 11200, "reference": None}],
    }
    payload.update(overrides)
    return CounterSaleRequest(**payload)


A_SALE = {"id": "s1", "capture_mode": "COUNTER", "sale_date": "2026-09-10",
          "tax_period": "092026", "is_aggregate": False}


class TestTheInvariant:
    def test_the_key_is_series_number_and_financial_year(self):
        # Stated as a test because everything downstream assumes it.
        same = dedupe_key("ph-1", "SALE_SERIAL", "CTR-", "2026", "42")
        assert same == dedupe_key("ph-1", "SALE_SERIAL", "CTR-", "2026", "42")
        # A different year restarts the sequence, so 42 is a different bill.
        assert same != dedupe_key("ph-1", "SALE_SERIAL", "CTR-", "2027", "42")
        # A different series is a different book.
        assert same != dedupe_key("ph-1", "SALE_SERIAL", "CTR2-", "2026", "42")
        # And workspaces never share a numbering space.
        assert same != dedupe_key("ph-2", "SALE_SERIAL", "CTR-", "2026", "42")

    @pytest.mark.anyio
    async def test_the_key_is_computed_from_the_serial_not_taken_from_the_client(self):
        captured = {}

        def save(*args, **kwargs):
            captured["key"] = args[1]
            return A_SALE, True, []

        with patch("db.repositories.sales_repository.save_counter_sale", side_effect=save):
            await record_counter_sale(a_bill(), Response(), USER)

        # 2026-09-10 is FY 2026; the serial parses to CTR- / 42.
        assert captured["key"] == dedupe_key("ph-1", "SALE_SERIAL", "CTR-", "2026", "42")

    @pytest.mark.anyio
    async def test_a_march_bill_belongs_to_the_previous_financial_year(self):
        captured = {}

        def save(*args, **kwargs):
            captured["key"] = args[1]
            return A_SALE, True, []

        with patch("db.repositories.sales_repository.save_counter_sale", side_effect=save):
            await record_counter_sale(a_bill(sale_date="2026-03-31"), Response(), USER)
        assert captured["key"] == dedupe_key("ph-1", "SALE_SERIAL", "CTR-", "2025", "42")

    @pytest.mark.anyio
    async def test_a_replayed_post_does_not_issue_a_second_bill(self):
        # The outbox retries after a timeout it never saw the answer to.
        with patch("db.repositories.sales_repository.save_counter_sale",
                   return_value=(A_SALE, False, [])):
            response = Response()
            body = await record_counter_sale(a_bill(), response, USER)
        assert body["created"] is False
        assert response.status_code == 200


class TestTheBillSurvives:
    @pytest.mark.anyio
    async def test_a_stock_shortfall_is_a_task_not_a_rejection(self):
        issues = [{"kind": "insufficient_stock", "line_id": "l1",
                   "detail": "CALPOL batch B1: sold 2, stock showed 1."}]
        with patch("db.repositories.sales_repository.save_counter_sale",
                   return_value=(A_SALE, True, issues)):
            response = Response()
            body = await record_counter_sale(a_bill(), response, USER)

        # 201, not 409. The bill is in a customer's hand; it exists.
        assert response.status_code == 201
        assert body["needs_reconciliation"] is True
        assert body["issues"][0]["kind"] == "insufficient_stock"

    @pytest.mark.anyio
    async def test_a_bill_for_a_filed_period_is_kept_and_flagged(self):
        issues = [{"kind": "period_filed", "line_id": None,
                   "detail": "Sep 2026 has already been filed."}]
        with patch("db.repositories.sales_repository.save_counter_sale",
                   return_value=(A_SALE, True, issues)):
            body = await record_counter_sale(a_bill(), Response(), USER)
        assert body["needs_reconciliation"] is True
        assert body["issues"][0]["kind"] == "period_filed"

    @pytest.mark.anyio
    async def test_a_clean_bill_reports_nothing_to_reconcile(self):
        with patch("db.repositories.sales_repository.save_counter_sale",
                   return_value=(A_SALE, True, [])):
            body = await record_counter_sale(a_bill(), Response(), USER)
        assert body["needs_reconciliation"] is False
        assert body["issues"] == []


class TestMalformedRequests:
    @pytest.mark.anyio
    async def test_a_serial_that_breaks_rule_46b_is_refused(self):
        # This one *can* be refused: it is malformed, and a device that
        # produced it has a bug rather than a bill worth keeping.
        with pytest.raises(HTTPException) as caught:
            await record_counter_sale(a_bill(serial="CTR 000042"), Response(), USER)
        assert caught.value.status_code == 400

    @pytest.mark.anyio
    async def test_an_unreadable_date_is_refused(self):
        with pytest.raises(HTTPException) as caught:
            await record_counter_sale(a_bill(sale_date="nonsense"), Response(), USER)
        assert caught.value.status_code == 400

    @pytest.mark.anyio
    async def test_nothing_is_written_when_the_request_is_refused(self):
        with patch("db.repositories.sales_repository.save_counter_sale") as save:
            with pytest.raises(HTTPException):
                await record_counter_sale(a_bill(serial="!!"), Response(), USER)
        save.assert_not_called()
