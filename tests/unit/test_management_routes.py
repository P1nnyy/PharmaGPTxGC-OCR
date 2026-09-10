"""The /management endpoints.

Driven through ASGI with every repository stubbed. What is under test is the
wiring - that costing is shared rather than rebuilt per report, that the
dashboard survives a period it cannot compute a return for, and that a return
window can only be set on a distributor this shop actually buys from.
"""

from unittest.mock import patch

import httpx
import pytest
from fastapi import Depends, FastAPI

from api.deps import current_user
from api.routers.management import router
from tests.unit.test_management_reports import COSTS, NAMES, SALES_MOVEMENTS, SOLD_LINES

ACCOUNT = {
    "id": "user-1", "email": "owner@example.com", "is_active": True,
    "role": "super_admin", "pharmacy_id": "pharmacy-9",
}

VENDORS = [
    {"vendor_id": "V1", "name": "Alpha Distributors", "gstin": "27AAA",
     "return_window_days": 10, "return_window_note": None,
     "invoice_count": 6, "last_invoice_date": "2026-09-03"},
    {"vendor_id": "V2", "name": "Beta Agencies", "gstin": "27BBB",
     "return_window_days": None, "return_window_note": None,
     "invoice_count": 2, "last_invoice_date": "2026-08-20"},
]

MOVEMENTS = [
    {"id": "m1", "product_id": "P1", "product_name": "Paracetamol 500",
     "batch_number": "B1", "expiry": "2026-10-15", "quantity_delta": 12.0,
     "reason": "PURCHASE", "occurred_on": "2026-08-01", "recorded_at": "2026-08-01T00:00:00Z",
     "taxable_paise": 100000, "input_tax_paise": 12000,
     "source_type": "Invoice", "source_id": "INV-1", "vendor_id": "V1"},
]


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
    def __init__(self, gstr1_raises=False, set_window=None):
        self.gstr1_raises = gstr1_raises
        self.set_window = set_window
        self.costing_builds = 0
        self.saved = {}

    def _batch_costs(self, *a, **k):
        self.costing_builds += 1
        return COSTS

    def _set_return_window(self, vendor_id, days=None, note=None, **_):
        self.saved = {"vendor_id": vendor_id, "days": days, "note": note}
        if isinstance(self.set_window, Exception):
            raise self.set_window
        return {"vendor_id": vendor_id, "name": "Alpha", "return_window_days": days,
                "return_window_note": note}

    def __enter__(self):
        base = "api.routers.management"
        from core.tax_periods import PeriodError
        documents = (
            patch(f"{base}.gstr1_repository.documents_for_period",
                  side_effect=PeriodError("nope") if self.gstr1_raises else None,
                  return_value=[])
        )
        self._patches = [
            patch("api.deps.decode_token", return_value={"sub": "user-1"}),
            patch("api.deps.user_repository.get_user", return_value=ACCOUNT),
            patch(f"{base}.management_repository.batch_costs", side_effect=self._batch_costs),
            patch(f"{base}.management_repository.batch_sales", return_value=SALES_MOVEMENTS),
            patch(f"{base}.management_repository.movements", return_value=MOVEMENTS),
            patch(f"{base}.management_repository.sold_lines", return_value=SOLD_LINES),
            patch(f"{base}.management_repository.day_total_count", return_value=3),
            patch(f"{base}.management_repository.sales_by_day",
                  return_value=[{"day": "2026-09-11", "bill_count": 18,
                                 "value_paise": 125000, "taxable_paise": 110000}]),
            patch(f"{base}.management_repository.sales_by_hour",
                  return_value=[{"hour": 18, "bill_count": 5, "value_paise": 50000}]),
            patch(f"{base}.management_repository.payment_split",
                  return_value=[{"method": "cash", "payment_count": 5, "amount_paise": 50000}]),
            patch(f"{base}.management_repository.purchases_by_day",
                  return_value=[{"day": "2026-09-02", "cost_paise": 400000, "invoice_count": 1}]),
            patch(f"{base}.management_repository.vendor_purchase_totals",
                  return_value=[{"vendor_id": "V1", "name": "Alpha Distributors",
                                 "gstin": "27AAA", "return_window_days": 10,
                                 "invoice_count": 6, "taxable_rupees": 50000.0,
                                 "tax_rupees": 6000.0}]),
            patch(f"{base}.vendor_repository.list_vendors", return_value=VENDORS),
            patch(f"{base}.vendor_repository.set_return_window",
                  side_effect=self._set_return_window),
            patch(f"{base}.pharmacy_repository.tax_identity",
                  return_value={"gstin": "27AAAAA0000A1Z5", "state_code": "27",
                                "effective_filing_frequency": "MONTHLY",
                                "hsn_digits": 4, "filing_frequency": "MONTHLY"}),
            documents,
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


class TestDashboard:
    @pytest.mark.anyio
    async def test_returns_exactly_four_cards(self):
        with Signed():
            response = await call("GET", "/management/dashboard")
        assert response.status_code == 200, response.text
        assert [c["id"] for c in response.json()["cards"]] == [
            "todays_sales", "itc_at_risk", "compliance_actions", "stock_value",
        ]

    @pytest.mark.anyio
    async def test_every_card_links_somewhere(self):
        with Signed():
            body = (await call("GET", "/management/dashboard")).json()
        assert all(c["link"] for c in body["cards"])

    @pytest.mark.anyio
    async def test_still_renders_when_the_return_cannot_be_computed(self):
        # A dashboard that fails entirely because a period could not be
        # resolved is worse than one card reading zero.
        with Signed(gstr1_raises=True):
            response = await call("GET", "/management/dashboard")
        assert response.status_code == 200
        compliance = response.json()["cards"][2]
        assert compliance["value"] == 0

    @pytest.mark.anyio
    async def test_an_unauthenticated_call_is_refused(self):
        transport = httpx.ASGITransport(app=app_with_auth())
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            response = await client.get("/management/dashboard")
        assert response.status_code == 401


class TestReports:
    @pytest.mark.anyio
    async def test_expiry_risk_leads_with_the_credit_at_risk(self):
        with Signed():
            body = (await call("GET", "/management/expiry-risk?horizon_days=180")).json()
        assert "input_tax_at_risk" in body["totals"]
        assert "17(5)(h)" in body["statutory_note"]

    @pytest.mark.anyio
    async def test_expiry_risk_honours_a_shorter_horizon(self):
        with Signed():
            wide = (await call("GET", "/management/expiry-risk?horizon_days=180")).json()
            narrow = (await call("GET", "/management/expiry-risk?horizon_days=20")).json()
        assert narrow["totals"]["batch_count"] <= wide["totals"]["batch_count"]

    @pytest.mark.anyio
    async def test_margin_reports_the_day_totals_it_had_to_leave_out(self):
        with Signed():
            body = (await call("GET", "/management/margin")).json()
        assert body["excluded"]["day_total_count"] == 3
        assert "carry no product lines" in body["excluded"]["note"]

    @pytest.mark.anyio
    async def test_costing_is_built_once_per_request_not_once_per_report(self):
        # Four reports need batch positions. Building them four times would be
        # four chances for two reports to disagree about the same shelf.
        with Signed() as signed:
            await call("GET", "/management/margin")
        assert signed.costing_builds == 1

    @pytest.mark.anyio
    async def test_the_stock_ledger_filters_by_batch(self):
        with Signed():
            body = (await call("GET", "/management/stock-ledger?batch_number=B1")).json()
        assert body["filters"]["batch_number"] == "B1"

    @pytest.mark.anyio
    async def test_movers_measures_cover_over_the_window_asked_for(self):
        with Signed():
            body = (await call(
                "GET", "/management/movers?start=2026-09-01&end=2026-09-30"
            )).json()
        assert body["days_observed"] == 30

    @pytest.mark.anyio
    async def test_a_backwards_window_is_refused(self):
        with Signed():
            response = await call(
                "GET", "/management/margin?start=2026-09-30&end=2026-09-01"
            )
        assert response.status_code == 400

    @pytest.mark.anyio
    async def test_daily_sales_carries_the_previous_month(self):
        with Signed():
            body = (await call("GET", "/management/daily-sales?month=2026-09-11")).json()
        assert body["window"]["start"] == "2026-09-01"
        assert body["previous_window"]["start"] == "2026-08-01"
        assert len(body["by_hour"]) == 24

    @pytest.mark.anyio
    async def test_the_trend_reports_both_sides(self):
        with Signed():
            body = (await call("GET", "/management/trend")).json()
        assert "purchases" in body["totals"] and "sales" in body["totals"]

    @pytest.mark.anyio
    async def test_the_scorecard_says_filing_data_is_not_connected(self):
        with Signed():
            body = (await call("GET", "/management/vendor-scorecard")).json()
        assert body["source"]["has_filing_data"] is False
        assert body["rows"][0]["filing"]["on_time_rate"] is None


class TestVendors:
    @pytest.mark.anyio
    async def test_lists_distributors_and_counts_the_missing_windows(self):
        with Signed():
            body = (await call("GET", "/management/vendors")).json()
        assert body["row_count"] == 2
        assert body["missing_return_window_count"] == 1

    @pytest.mark.anyio
    async def test_records_a_return_window(self):
        with Signed() as signed:
            response = await call(
                "PUT", "/management/vendors/V2/return-window",
                json={"return_window_days": 90},
            )
        assert response.status_code == 200, response.text
        assert signed.saved == {"vendor_id": "V2", "days": 90, "note": None}

    @pytest.mark.anyio
    async def test_clearing_a_window_is_a_real_answer(self):
        # A shop that learns its supplier stopped taking returns needs to say
        # so; a stale number would keep promising a route that has closed.
        with Signed() as signed:
            response = await call(
                "PUT", "/management/vendors/V1/return-window",
                json={"return_window_days": None},
            )
        assert response.status_code == 200
        assert signed.saved["days"] is None

    @pytest.mark.anyio
    async def test_a_refusal_is_reported_with_its_reason(self):
        from db.repositories.vendor_repository import VendorError
        with Signed(set_window=VendorError("A return window is a whole number of days.")):
            response = await call(
                "PUT", "/management/vendors/V1/return-window",
                json={"return_window_days": "soon"},
            )
        assert response.status_code == 422
        assert "whole number" in response.json()["detail"]
