"""The /tax-periods endpoints.

Driven through the ASGI app rather than by calling the functions, because what
is under test is mostly the wiring: that a bad period is refused before it
reaches the engine, that a close is refused while blocking items stand, and
that closing a QRMP period locks the whole quarter rather than the month
somebody clicked.

`httpx.ASGITransport` rather than `TestClient` - the pinned starlette and a
current httpx disagree about the `app` keyword. It also skips lifespan, so
nothing here opens the production Neo4j the way a real startup would.
"""

from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
from fastapi import Depends, FastAPI

from api.deps import current_user
from api.routers.tax_periods import router
from services.gstr1.model import (
    DocumentStatus,
    OutwardDocument,
    OutwardLine,
    SupplyClass,
)

IDENTITY = {
    "gstin": "27AAAAA0000A1Z5",
    "pan": "AAAAA0000A",
    "state_code": "27",
    "legal_name": "Test Pharmacy",
    "filing_frequency": "MONTHLY",
    "effective_filing_frequency": "MONTHLY",
    "aato_paise": 2_00_00_000_00,
    "hsn_digit_policy": "FOUR_DIGIT",
    "hsn_digits": 4,
    "hsn_policy_is_declared": True,
}

ACCOUNT = {
    "id": "user-1",
    "email": "owner@example.com",
    "is_active": True,
    "role": "super_admin",
    "pharmacy_id": "pharmacy-9",
}


def a_clean_bill():
    """One intra-state counter bill that trips no validation at all."""
    return OutwardDocument(
        document_id="D1",
        sale_date="2026-09-05",
        tax_period="092026",
        supplier_state_code="27",
        place_of_supply_state_code="27",
        bill_number="CTR-000001",
        series_prefix="CTR-",
        serial_sequence=1,
        status=DocumentStatus.CONFIRMED,
        lines=(
            OutwardLine(
                line_id="L1", product_id="P1", product_name="Paracetamol",
                hsn="3004", uqc="TBS", quantity=Decimal("2"),
                supply_class=SupplyClass.TAXABLE, rate_bp=1200,
                taxable_paise=100000, cgst_paise=6000, sgst_paise=6000,
            ),
        ),
        taxable_paise=100000, cgst_paise=6000, sgst_paise=6000,
        grand_total_paise=112000,
    )


def a_bill_with_a_series_gap():
    """A second bill at sequence 3, leaving 2 missing."""
    bill = a_clean_bill()
    return OutwardDocument(
        **{
            **bill.__dict__,
            "document_id": "D2",
            "bill_number": "CTR-000003",
            "serial_sequence": 3,
        }
    )


def app_with_auth():
    app = FastAPI()
    app.include_router(router, dependencies=[Depends(current_user)])
    return app


async def call(method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app_with_auth())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        return await client.request(
            method, path, headers={"Authorization": "Bearer any-token"}, **kwargs
        )


class Signed:
    """Signs the caller in and stubs everything that would touch the graph."""

    def __init__(self, documents=(), period_state=None, own_sales=0):
        self.documents = list(documents)
        self.period_state = period_state or {"period": "092026", "status": "OPEN", "closed_at": None}
        self.own_sales = own_sales
        self.closed_with = {}

    def _close(self, months, payload, summary, closed_by=None, acknowledged=None, **_):
        self.closed_with = {
            "months": months, "payload": payload, "summary": summary,
            "closed_by": closed_by, "acknowledged": acknowledged,
        }
        return [{"period": m, "status": "CLOSED"} for m in months]

    def __enter__(self):
        self._patches = [
            patch("api.deps.decode_token", return_value={"sub": "user-1"}),
            patch("api.deps.user_repository.get_user", return_value=ACCOUNT),
            patch("api.routers.tax_periods.pharmacy_repository.tax_identity",
                  return_value=dict(IDENTITY)),
            patch("api.routers.tax_periods.gstr1_repository.documents_for_period",
                  return_value=self.documents),
            patch("api.routers.tax_periods.gstr1_repository.own_sales_for_financial_year",
                  return_value=self.own_sales),
            patch("api.routers.tax_periods.sales_repository.get_period",
                  return_value=self.period_state),
            patch("api.routers.tax_periods.sales_repository.close_period",
                  side_effect=self._close),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


class TestPreview:
    @pytest.mark.anyio
    async def test_refuses_something_that_is_not_a_period(self):
        with Signed():
            response = await call("GET", "/tax-periods/september")
        assert response.status_code == 400
        assert "MMYYYY" in response.json()["detail"]

    @pytest.mark.anyio
    async def test_refuses_an_unpadded_month(self):
        # 92026 is ambiguous against a two-digit year, and guessing would file
        # a return into the wrong month.
        with Signed():
            response = await call("GET", "/tax-periods/92026")
        assert response.status_code == 400

    @pytest.mark.anyio
    async def test_an_unauthenticated_call_is_refused(self):
        transport = httpx.ASGITransport(app=app_with_auth())
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            response = await client.get("/tax-periods/092026")
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_returns_the_tables_and_totals_in_rupees(self):
        with Signed(documents=[a_clean_bill()]):
            response = await call("GET", "/tax-periods/092026")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["period"]["label"] == "Sep 2026"
        assert body["period"]["status"] == "OPEN"
        assert body["totals"]["taxable"] == 1000.00
        assert body["totals"]["cgst"] == 60.00
        assert body["tables"]["b2cs"][0]["rate"] == 12
        assert body["can_close"] is True

    @pytest.mark.anyio
    async def test_an_empty_period_is_a_nil_return_that_still_computes(self):
        with Signed(documents=[]):
            response = await call("GET", "/tax-periods/092026")
        body = response.json()
        assert body["is_nil_return"] is True
        assert body["totals"]["supplies"] == 0
        # Table 8 still states all four rows, at zero.
        assert len(body["tables"]["nil_exempt"]) == 4
        assert body["can_close"] is True

    @pytest.mark.anyio
    async def test_a_quarterly_filer_is_told_the_window(self):
        identity = {**IDENTITY, "effective_filing_frequency": "QUARTERLY",
                    "filing_frequency": "QUARTERLY"}
        with Signed(documents=[a_clean_bill()]):
            with patch("api.routers.tax_periods.pharmacy_repository.tax_identity",
                       return_value=identity):
                response = await call("GET", "/tax-periods/092026")
        period = response.json()["period"]
        assert period["frequency"] == "QUARTERLY"
        assert period["months"] == ["072026", "082026", "092026"]
        assert period["label"] == "Jul-Sep 2026"


class TestClose:
    @pytest.mark.anyio
    async def test_refuses_while_a_blocking_item_stands(self):
        with Signed(documents=[a_clean_bill(), a_bill_with_a_series_gap()]):
            response = await call("POST", "/tax-periods/092026/close", json={})
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "cannot be closed" in detail["message"]
        assert any(i["code"] == "SERIES_GAP" for i in detail["outstanding"])

    @pytest.mark.anyio
    async def test_closes_once_the_blocking_item_is_acknowledged(self):
        documents = [a_clean_bill(), a_bill_with_a_series_gap()]
        with Signed(documents=documents) as signed:
            refused = await call("POST", "/tax-periods/092026/close", json={})
            ids = [i["id"] for i in refused.json()["detail"]["outstanding"]]
            response = await call(
                "POST", "/tax-periods/092026/close", json={"acknowledged": ids}
            )
        assert response.status_code == 200, response.text
        assert response.json()["closed"] is True
        assert signed.closed_with["acknowledged"] == sorted(ids)

    @pytest.mark.anyio
    async def test_closes_a_clean_period_with_no_acknowledgement(self):
        with Signed(documents=[a_clean_bill()]) as signed:
            response = await call("POST", "/tax-periods/092026/close", json={})
        assert response.status_code == 200, response.text
        assert signed.closed_with["months"] == ["092026"]
        # The payload is stored with the lock so the return stays reproducible.
        assert signed.closed_with["payload"]["fp"] == "092026"
        assert signed.closed_with["closed_by"] == "user-1"

    @pytest.mark.anyio
    async def test_closing_a_qrmp_period_locks_the_whole_quarter(self):
        identity = {**IDENTITY, "effective_filing_frequency": "QUARTERLY",
                    "filing_frequency": "QUARTERLY"}
        with Signed(documents=[a_clean_bill()]) as signed:
            with patch("api.routers.tax_periods.pharmacy_repository.tax_identity",
                       return_value=identity):
                response = await call("POST", "/tax-periods/092026/close", json={})
        assert response.status_code == 200, response.text
        # Not just September: leaving July and August open would leave records
        # editable after their figures had gone to the portal.
        assert signed.closed_with["months"] == ["072026", "082026", "092026"]

    @pytest.mark.anyio
    async def test_refuses_to_close_a_period_twice(self):
        closed = {"period": "092026", "status": "CLOSED", "closed_at": "2026-10-02T10:00:00Z"}
        with Signed(documents=[a_clean_bill()], period_state=closed):
            response = await call("POST", "/tax-periods/092026/close", json={})
        assert response.status_code == 409
        assert "already been closed" in response.json()["detail"]

    @pytest.mark.anyio
    async def test_ignores_an_acknowledgement_that_no_longer_applies(self):
        # An id for a problem that has since been fixed must not close a
        # period that has a different problem now.
        with Signed(documents=[a_clean_bill(), a_bill_with_a_series_gap()]):
            response = await call(
                "POST", "/tax-periods/092026/close", json={"acknowledged": ["deadbeefdeadbeef"]}
            )
        assert response.status_code == 422


class TestPayload:
    @pytest.mark.anyio
    async def test_an_open_period_is_computed_fresh(self):
        with Signed(documents=[a_clean_bill()]):
            response = await call("GET", "/tax-periods/092026/payload")
        body = response.json()
        assert body["gstin"] == "27AAAAA0000A1Z5"
        assert body["fp"] == "092026"
        assert body["b2cs"][0]["txval"] == 1000.00

    @pytest.mark.anyio
    async def test_a_closed_period_returns_what_was_filed(self):
        # Not a fresh computation. When the portal disagrees months later the
        # question is what was actually sent.
        stored = {
            "period": "092026",
            "status": "CLOSED",
            "payload_json": '{"gstin": "27AAAAA0000A1Z5", "fp": "092026", "b2cs": []}',
        }
        with Signed(documents=[a_clean_bill()], period_state=stored):
            response = await call("GET", "/tax-periods/092026/payload")
        assert response.json()["b2cs"] == []
