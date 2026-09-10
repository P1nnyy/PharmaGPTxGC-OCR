"""The /statutory endpoints.

Driven through ASGI, with every repository stubbed - nothing here opens a
database. What is under test is the wiring: that the pack comes back with its
cross-checks already run, that an export is the same figures in another
container, that a drill resolves what was clicked, and that the ledger refuses
a reversal it cannot justify.
"""

from unittest.mock import patch

import httpx
import pytest
from fastapi import Depends, FastAPI

from api.deps import current_user
from api.routers.statutory import router
from tests.unit.test_gstr1_synthetic_month import IDENTITY, PERIOD
from tests.unit.test_gstr1_synthetic_month import september as _september

ACCOUNT = {
    "id": "user-1", "email": "owner@example.com", "is_active": True,
    "role": "super_admin", "pharmacy_id": "pharmacy-9",
}

PURCHASES = [
    {"invoice_id": "P1", "invoice_number": "SUP-001", "invoice_date": "2026-09-03",
     "seller_name": "Distributor A", "seller_gstin": "27CCCCC0000C1Z5",
     "status": "verified", "taxable_paise": 1000000, "discount_paise": 0,
     "cgst_paise": 60000, "sgst_paise": 60000, "igst_paise": 0,
     "roundoff_paise": 0, "grand_total_paise": 1120000},
]
PAYMENTS = [{"sale_id": "D1", "method": "cash", "amount_paise": 132000,
             "status": "CONFIRMED", "document_type": "INVOICE", "reference": None}]
HSN_LINES = [{"hsn": "3004", "gst_percent": 12.0, "pack": "10x10", "line_count": 3,
              "taxable_paise": 1000000, "quantity": 30.0, "invoice_ids": ["P1"]}]


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

    def __init__(self, reversals=(), documents=None, record=None):
        self.reversals = list(reversals)
        self.documents = _september.__wrapped__() if documents is None else documents
        self.record = record
        self.recorded = {}

    def _record(self, **kwargs):
        self.recorded = kwargs
        if isinstance(self.record, Exception):
            raise self.record
        return {"id": "R-new", **kwargs}

    def __enter__(self):
        base = "api.routers.statutory"
        self._patches = [
            patch("api.deps.decode_token", return_value={"sub": "user-1"}),
            patch("api.deps.user_repository.get_user", return_value=ACCOUNT),
            patch(f"{base}.pharmacy_repository.tax_identity", return_value=dict(IDENTITY)),
            patch(f"{base}.gstr1_repository.documents_for_period", return_value=self.documents),
            patch(f"{base}.gstr1_repository.own_sales_for_financial_year", return_value=31100000),
            patch(f"{base}.statutory_repository.payments_for_window", return_value=PAYMENTS),
            patch(f"{base}.statutory_repository.purchase_invoices", return_value=PURCHASES),
            patch(f"{base}.statutory_repository.purchase_rate_blocks", return_value=[]),
            patch(f"{base}.statutory_repository.purchase_hsn_lines", return_value=HSN_LINES),
            patch(f"{base}.statutory_repository.documents_by_id",
                  return_value=[{"id": "D1", "number": "CTR-000001"}]),
            patch(f"{base}.itc_repository.list_reversals", return_value=self.reversals),
            patch(f"{base}.itc_repository.totals_by_table", return_value={}),
            patch(f"{base}.itc_repository.record_reversal", side_effect=self._record),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


class TestReportPack:
    @pytest.mark.anyio
    async def test_returns_all_seven_reports(self):
        with Signed():
            response = await call("GET", f"/statutory/{PERIOD}")
        assert response.status_code == 200, response.text
        assert set(response.json()["reports"]) == {
            "gstr1", "gstr3b", "purchase_register", "sales_register",
            "hsn_summary", "document_series", "itc_reversals",
        }

    @pytest.mark.anyio
    async def test_cross_checks_come_back_with_the_pack(self):
        # In the response rather than behind their own call, so a client that
        # renders the pack has already been told whether it reconciles.
        with Signed():
            body = (await call("GET", f"/statutory/{PERIOD}")).json()
        assert len(body["cross_checks"]) == 4
        assert body["checks_pass"] is True

    @pytest.mark.anyio
    async def test_refuses_something_that_is_not_a_period(self):
        with Signed():
            response = await call("GET", "/statutory/september")
        assert response.status_code == 400

    @pytest.mark.anyio
    async def test_an_unauthenticated_call_is_refused(self):
        transport = httpx.ASGITransport(app=app_with_auth())
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            response = await client.get(f"/statutory/{PERIOD}")
        assert response.status_code == 401

    @pytest.mark.anyio
    async def test_a_rate_filter_crosses_the_wire_as_a_percentage(self):
        # People type 5, the engine computes in basis points.
        with Signed():
            body = (await call("GET", f"/statutory/{PERIOD}?rate=5")).json()
        register = body["reports"]["sales_register"]
        assert register["filters_applied"]["rate"] == 5.0
        assert register["row_count"] == 1


class TestExports:
    @pytest.mark.anyio
    async def test_csv_carries_the_period_and_the_figures(self):
        with Signed():
            response = await call("GET", f"/statutory/{PERIOD}/export/purchase_register?fmt=csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        text = response.content.decode("utf-8-sig")
        assert "Sep 2026" in text
        assert "SUP-001" in text
        # Money as a plain number: an accountant's first action is to sum it.
        assert "10000.0" in text

    @pytest.mark.anyio
    async def test_csv_starts_with_a_bom_so_excel_reads_the_rupee_sign(self):
        with Signed():
            response = await call("GET", f"/statutory/{PERIOD}/export/purchase_register?fmt=csv")
        assert response.content.startswith(b"\xef\xbb\xbf")

    @pytest.mark.anyio
    async def test_xlsx_is_a_real_workbook(self):
        with Signed():
            response = await call("GET", f"/statutory/{PERIOD}/export/sales_register?fmt=xlsx")
        assert response.status_code == 200
        # xlsx is a zip; the magic bytes are the cheapest honest check.
        assert response.content[:2] == b"PK"
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats"
        )

    @pytest.mark.anyio
    async def test_the_filename_names_the_shop_and_the_period(self):
        with Signed():
            response = await call("GET", f"/statutory/{PERIOD}/export/document_series?fmt=xlsx")
        disposition = response.headers["content-disposition"]
        assert "27AAAAA0000A1Z5" in disposition and "Sep-2026" in disposition

    @pytest.mark.anyio
    async def test_every_report_exports_in_both_formats(self):
        with Signed():
            for report_id in ("gstr1", "gstr3b", "purchase_register", "sales_register",
                              "hsn_summary", "hsn_inward", "document_series", "itc_reversals"):
                for fmt in ("csv", "xlsx"):
                    response = await call(
                        "GET", f"/statutory/{PERIOD}/export/{report_id}?fmt={fmt}"
                    )
                    assert response.status_code == 200, f"{report_id}.{fmt}: {response.text[:200]}"
                    assert len(response.content) > 0

    @pytest.mark.anyio
    async def test_an_unknown_report_is_a_404_not_an_empty_file(self):
        with Signed():
            response = await call("GET", f"/statutory/{PERIOD}/export/nonsense?fmt=csv")
        assert response.status_code == 404


class TestDrill:
    @pytest.mark.anyio
    async def test_resolves_the_drill_object_a_figure_carried(self):
        # The client hands back exactly what it was given, which is what makes
        # every number clickable without the UI knowing how a report was built.
        with Signed():
            response = await call(
                "POST", "/statutory/drill",
                json={"kind": "SALES", "filters": {"ids": ["D1"]}, "count": 1},
            )
        assert response.status_code == 200
        assert response.json()["resolved_by"] == "ids"
        assert response.json()["rows"][0]["number"] == "CTR-000001"

    @pytest.mark.anyio
    async def test_resolves_a_predicate_when_there_are_no_ids(self):
        with Signed():
            response = await call(
                "POST", "/statutory/drill",
                json={"kind": "SALES", "filters": {"periods": [PERIOD], "status": "CONFIRMED"}},
            )
        assert response.status_code == 200
        assert response.json()["resolved_by"] == "filters"

    @pytest.mark.anyio
    async def test_refuses_a_kind_it_cannot_resolve(self):
        with Signed():
            response = await call(
                "POST", "/statutory/drill", json={"kind": "PAYROLL", "filters": {}}
            )
        assert response.status_code == 400

    @pytest.mark.anyio
    async def test_refuses_a_drill_with_nothing_to_resolve_against(self):
        with Signed():
            response = await call("POST", "/statutory/drill", json={"kind": "SALES", "filters": {}})
        assert response.status_code == 400


class TestReversals:
    @pytest.mark.anyio
    async def test_serves_the_triggers_with_their_rules(self):
        # Served rather than hard-coded in the UI, so the form and the ledger
        # cannot disagree about which provision a trigger cites.
        with Signed():
            body = (await call("GET", "/statutory/reversals/triggers")).json()
        triggers = {t["trigger"]: t for t in body["triggers"]}
        assert triggers["EXPIRED_STOCK"]["statutory_reference"] == "Section 17(5)(h)"
        assert triggers["EXPIRED_STOCK"]["gstr3b_table"] == "4(B)(1)"
        assert triggers["NON_PAYMENT_180_DAYS"]["is_reclaimable"] is True

    @pytest.mark.anyio
    async def test_records_a_reversal_against_its_source_document(self):
        with Signed() as signed:
            response = await call(
                "POST", "/statutory/reversals",
                json={"trigger": "EXPIRED_STOCK", "tax_period": PERIOD,
                      "cgst_paise": 1200, "sgst_paise": 1200,
                      "source_type": "INVOICE", "source_id": "P1"},
            )
        assert response.status_code == 201, response.text
        assert signed.recorded["source_id"] == "P1"
        assert signed.recorded["recorded_by"] == "user-1"

    @pytest.mark.anyio
    async def test_a_ledger_refusal_is_reported_with_its_reason(self):
        from db.repositories.itc_repository import ItcLedgerError
        refusal = ItcLedgerError("A reversal has to name the document it came from.")
        with Signed(record=refusal):
            response = await call(
                "POST", "/statutory/reversals",
                json={"trigger": "EXPIRED_STOCK", "tax_period": PERIOD, "cgst_paise": 100},
            )
        assert response.status_code == 422
        assert "name the document" in response.json()["detail"]

    @pytest.mark.anyio
    async def test_lists_the_ledger_for_a_period(self):
        rows = [{"id": "R1", "gstr3b_table": "4(B)(1)", "total_paise": 2400}]
        with Signed(reversals=rows):
            body = (await call("GET", f"/statutory/reversals/{PERIOD}")).json()
        assert body["row_count"] == 1
        assert body["period"] == "Sep 2026"

    @pytest.mark.anyio
    async def test_the_reversal_routes_are_not_shadowed_by_the_period_route(self):
        # `/statutory/{period}` matches any single segment; these must still
        # reach their own handlers.
        with Signed():
            triggers = await call("GET", "/statutory/reversals/triggers")
        assert triggers.status_code == 200
        assert "triggers" in triggers.json()
