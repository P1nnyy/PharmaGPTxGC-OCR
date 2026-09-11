"""The /sales routes, with the graph stubbed.

What is under test is the behaviour a caller depends on: that posting the same
day twice does not declare the same output tax twice, that a filed period
refuses edits, and that every sale carries an explicit statement of what it can
be used to claim.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException, Response

from api.routers.sales import create_day_total, edit_day_total, file_period, period_status
from core.tenancy import tenant_scope
from db.repositories.sales_repository import PeriodFiledError
from api.routers.sales import FilePeriodRequest
from models.sales import DayTotalRequest

USER = {"id": "u-1", "email": "owner@example.com", "name": "Owner",
        "role": "super_admin", "pharmacy_id": "ph-1", "is_active": True}


@pytest.fixture(autouse=True)
def workspace():
    with tenant_scope("ph-1"):
        yield


@pytest.fixture(autouse=True)
def no_audit():
    with patch("api.routers.sales.audit_repository.record"):
        yield


def a_day(**overrides) -> DayTotalRequest:
    payload = {
        "sale_date": "2026-09-10",
        "rate_blocks": [{"rate_bp": 1200, "gross_paise": 112000}],
        "exempt_paise": 0,
        "nil_rated_paise": 0,
        "non_gst_paise": 0,
        "payments": [{"method": "cash", "amount_paise": 112000, "reference": None}],
    }
    payload.update(overrides)
    return DayTotalRequest(**payload)


def a_sale(**overrides) -> dict:
    base = {
        "id": "sale-1",
        "capture_mode": "DAY_TOTAL",
        "document_class": "INVOICE_CUM_BILL_OF_SUPPLY",
        "status": "CONFIRMED",
        "sale_date": "2026-09-10",
        "tax_period": "092026",
        "taxable_paise": 100000,
        "grand_total_paise": 112000,
        # Stored by the ingest path, not inferred on read: a day total has no
        # lines behind it whatever its capture mode says.
        "is_aggregate": True,
    }
    base.update(overrides)
    return base


class TestCreateDayTotal:
    @pytest.mark.anyio
    async def test_creates_and_answers_201(self):
        with patch("db.repositories.sales_repository.upsert_sale", return_value=(a_sale(), True)):
            response = Response()
            body = await create_day_total(a_day(), response, USER)
        assert response.status_code == 201
        assert body["created"] is True
        assert body["taxable_paise"] == 100000

    @pytest.mark.anyio
    async def test_reposting_the_same_day_does_not_declare_it_twice(self):
        # The whole point of the dedupe key: a retry after a timeout must not
        # produce a second day total for the same date.
        with patch("db.repositories.sales_repository.upsert_sale", return_value=(a_sale(), False)):
            response = Response()
            body = await create_day_total(a_day(), response, USER)
        assert response.status_code == 200
        assert body["created"] is False
        assert "already recorded" in body["message"]

    @pytest.mark.anyio
    async def test_a_filed_period_refuses_the_write(self):
        with patch(
            "db.repositories.sales_repository.upsert_sale",
            side_effect=PeriodFiledError("Sep 2026 has been filed."),
        ):
            with pytest.raises(HTTPException) as caught:
                await create_day_total(a_day(), Response(), USER)
        assert caught.value.status_code == 409
        assert "filed" in caught.value.detail

    @pytest.mark.anyio
    async def test_a_split_that_does_not_add_up_is_a_400(self):
        bad = a_day(payments=[{"method": "cash", "amount_paise": 1, "reference": None}])
        with pytest.raises(HTTPException) as caught:
            await create_day_total(bad, Response(), USER)
        assert caught.value.status_code == 400
        assert "payment" in caught.value.detail.lower()

    @pytest.mark.anyio
    async def test_nothing_is_written_when_the_figures_are_rejected(self):
        bad = a_day(payments=[{"method": "cash", "amount_paise": 1, "reference": None}])
        with patch("db.repositories.sales_repository.upsert_sale") as write:
            with pytest.raises(HTTPException):
                await create_day_total(bad, Response(), USER)
        write.assert_not_called()


class TestReportingCaveat:
    @pytest.mark.anyio
    async def test_a_day_total_says_it_has_no_lines_or_stock(self):
        # Downstream must not be able to compute a margin from this and
        # present it as precise.
        with patch("db.repositories.sales_repository.upsert_sale", return_value=(a_sale(), True)):
            body = await create_day_total(a_day(), Response(), USER)
        reporting = body["reporting"]
        assert reporting["is_aggregate"] is True
        assert reporting["has_line_items"] is False
        assert reporting["moves_stock"] is False
        assert "B2CS" in reporting["note"]

    @pytest.mark.anyio
    async def test_a_counter_sale_carries_lines_and_stock(self):
        counter = a_sale(capture_mode="COUNTER", is_aggregate=False)
        with patch("db.repositories.sales_repository.upsert_sale", return_value=(counter, True)):
            body = await create_day_total(a_day(), Response(), USER)
        assert body["reporting"]["has_line_items"] is True
        assert body["reporting"]["moves_stock"] is True
        assert body["reporting"]["note"] is None


class TestEditing:
    @pytest.mark.anyio
    async def test_corrects_an_open_period(self):
        with patch("db.repositories.sales_repository.update_sale", return_value=a_sale(taxable_paise=90000)):
            body = await edit_day_total("sale-1", a_day(), USER)
        assert body["taxable_paise"] == 90000

    @pytest.mark.anyio
    async def test_refuses_once_the_period_is_filed(self):
        with patch(
            "db.repositories.sales_repository.update_sale",
            side_effect=PeriodFiledError("Sep 2026 has been filed."),
        ):
            with pytest.raises(HTTPException) as caught:
                await edit_day_total("sale-1", a_day(), USER)
        assert caught.value.status_code == 409

    @pytest.mark.anyio
    async def test_a_missing_sale_is_a_404(self):
        with patch("db.repositories.sales_repository.update_sale", side_effect=LookupError("No sale")):
            with pytest.raises(HTTPException) as caught:
                await edit_day_total("nope", a_day(), USER)
        assert caught.value.status_code == 404


class TestPeriods:
    @pytest.mark.anyio
    async def test_filing_closes_the_period(self):
        with patch(
            "db.repositories.sales_repository.mark_period_filed",
            return_value={"period": "092026", "filed_at": "2026-10-01T00:00:00Z", "filed_by": "u-1"},
        ):
            body = await file_period(FilePeriodRequest(period="092026"), USER)
        assert body["label"] == "Sep 2026"
        assert body["filed_at"]

    @pytest.mark.anyio
    async def test_refuses_a_malformed_period(self):
        with pytest.raises(HTTPException) as caught:
            await file_period(FilePeriodRequest(period="2026-09"), USER)
        assert caught.value.status_code == 400

    @pytest.mark.anyio
    async def test_reports_whether_a_period_is_open(self):
        with patch("db.repositories.sales_repository.is_period_filed", return_value=True):
            body = await period_status("092026", USER)
        assert body["filed"] is True
        assert body["label"] == "Sep 2026"
