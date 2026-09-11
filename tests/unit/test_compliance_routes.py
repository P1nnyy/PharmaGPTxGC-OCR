"""The /compliance endpoints.

The one that matters most is what is *absent*: there is no endpoint here that
files anything, and `POST /compliance/filings` records evidence of a filing
that already happened rather than performing one. A test pins that, because it
is the kind of boundary that erodes by accident.
"""

from unittest.mock import patch

import httpx
import pytest
from fastapi import Depends, FastAPI

from api.deps import current_user
from api.routers.compliance import router

ACCOUNT = {
    "id": "user-1", "email": "owner@example.com", "is_active": True,
    "role": "super_admin", "pharmacy_id": "pharmacy-9",
}

IDENTITY = {
    "gstin": "27AAAAA0000A1Z5", "state_code": "27", "legal_name": "Test Pharmacy",
    "filing_frequency": "MONTHLY", "effective_filing_frequency": "MONTHLY",
    "hsn_digits": 4, "hsn_policy_is_declared": True, "aato_paise": 2_00_00_000_00,
}


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
    def __init__(self, identity=None, filings=(), settings=None,
                 period_state=None, record=None):
        self.identity = identity or dict(IDENTITY)
        self.filings = list(filings)
        self.settings = settings or {
            "enabled": False, "days_before": [7, 3, 1, 0],
            "channel": "IN_APP", "is_default": True,
        }
        self.period_state = period_state or {"status": "OPEN"}
        self.record = record
        self.recorded = {}

    def _record(self, **kwargs):
        self.recorded = kwargs
        if isinstance(self.record, Exception):
            raise self.record
        return {"id": "f-new", **kwargs}

    def __enter__(self):
        base = "api.routers.compliance"
        self._patches = [
            patch("api.deps.decode_token", return_value={"sub": "user-1"}),
            patch("api.deps.user_repository.get_user", return_value=ACCOUNT),
            patch(f"{base}.pharmacy_repository.tax_identity", return_value=self.identity),
            patch(f"{base}.gstr1_repository.documents_for_period", return_value=[]),
            patch(f"{base}.sales_repository.get_period", return_value=self.period_state),
            patch(f"{base}.compliance_repository.filings_for_periods",
                  return_value=self.filings),
            patch(f"{base}.compliance_repository.live_filing", return_value=None),
            patch(f"{base}.compliance_repository.reminder_settings",
                  return_value=self.settings),
            patch(f"{base}.compliance_repository.set_reminder_settings",
                  return_value={**self.settings, "enabled": True}),
            patch(f"{base}.compliance_repository.record_filing", side_effect=self._record),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


class TestNothingFiles:
    def test_no_endpoint_files_a_return(self):
        # The boundary this whole milestone is defined by. Filing is a later
        # milestone, will be OTP-gated, and must never be reachable by
        # accident from here.
        paths = {r.path for r in router.routes}
        assert not any("submit" in p or "file-return" in p or "gsp" in p for p in paths)
        methods = {(tuple(sorted(r.methods)), r.path) for r in router.routes}
        writes = {p for m, p in methods if "POST" in m or "PUT" in m}
        # Only two writes: recording evidence, and reminder settings.
        assert writes == {"/compliance/filings", "/compliance/reminders"}

    @pytest.mark.anyio
    async def test_recording_a_filing_records_rather_than_files(self):
        with Signed() as signed:
            response = await call(
                "POST", "/compliance/filings",
                json={"period": "092026", "return_type": "GSTR1",
                      "arn": "AA270926000001X", "filed_at": "2026-10-09T10:00:00Z"},
            )
        assert response.status_code == 201, response.text
        assert signed.recorded["arn"] == "AA270926000001X"
        assert signed.recorded["filed_by"] == "user-1"


class TestNextAction:
    @pytest.mark.anyio
    async def test_names_one_thing(self):
        with Signed():
            body = (await call("GET", "/compliance/next-action")).json()
        assert "next_action" in body
        assert isinstance(body["next_action"], (dict, type(None)))

    @pytest.mark.anyio
    async def test_carries_the_time_bar_counts_for_the_home_screen(self):
        with Signed():
            body = (await call("GET", "/compliance/next-action")).json()
        assert set(body["time_bar"]) == {
            "already_barred_count", "closing_soon_count", "has_anything",
        }

    @pytest.mark.anyio
    async def test_an_unauthenticated_call_is_refused(self):
        transport = httpx.ASGITransport(app=app_with_auth())
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            response = await client.get("/compliance/next-action")
        assert response.status_code == 401


class TestCalendar:
    @pytest.mark.anyio
    async def test_a_monthly_shop_gets_three_obligations_a_month(self):
        with Signed():
            body = (await call("GET", "/compliance/calendar?financial_year=2026")).json()
        assert len(body["items"]) == 36
        assert body["effective_filing_frequency"] == "MONTHLY"

    @pytest.mark.anyio
    async def test_a_qrmp_shop_gets_a_different_schedule_not_a_shifted_one(self):
        qrmp = {**IDENTITY, "filing_frequency": "QUARTERLY",
                "effective_filing_frequency": "QUARTERLY"}
        with Signed(identity=qrmp):
            body = (await call("GET", "/compliance/calendar?financial_year=2026")).json()
        kinds = [i["kind"] for i in body["items"]]
        assert kinds.count("GSTR1") == 4
        assert kinds.count("PMT06") == 8
        assert kinds.count("IFF") == 8

    @pytest.mark.anyio
    async def test_warns_when_nobody_has_set_the_filing_frequency(self):
        # A QRMP shop's dates are completely different, so assuming monthly
        # without saying so would produce a confident wrong calendar.
        unset = {**IDENTITY, "filing_frequency": None}
        with Signed(identity=unset):
            body = (await call("GET", "/compliance/calendar")).json()
        assert body["frequency_is_set"] is False

    @pytest.mark.anyio
    async def test_the_state_changes_the_qrmp_3b_date(self):
        for state, day in (("27", "-22"), ("07", "-24")):
            identity = {**IDENTITY, "state_code": state,
                        "effective_filing_frequency": "QUARTERLY"}
            with Signed(identity=identity):
                body = (await call("GET", "/compliance/calendar?financial_year=2026")).json()
            due = next(i["due_date"] for i in body["items"]
                       if i["kind"] == "GSTR3B" and i["period"] == "092026")
            assert due.endswith(day)


class TestTimeline:
    @pytest.mark.anyio
    async def test_returns_all_eight_stages(self):
        with Signed():
            body = (await call("GET", "/compliance/timeline/092026")).json()
        assert len(body["stages"]) == 8
        assert body["stages"][0]["id"] == "sales_captured"

    @pytest.mark.anyio
    async def test_2b_and_ims_report_blocked_on_something_external(self):
        with Signed():
            body = (await call("GET", "/compliance/timeline/092026")).json()
        found = {s["id"]: s for s in body["stages"]}
        assert found["reconciled_2b"]["state"] == "BLOCKED"
        assert found["ims_actioned"]["state"] == "BLOCKED"

    @pytest.mark.anyio
    async def test_refuses_something_that_is_not_a_period(self):
        with Signed():
            response = await call("GET", "/compliance/timeline/september")
        assert response.status_code == 400


class TestTimeBar:
    @pytest.mark.anyio
    async def test_cites_the_sections_and_separates_lost_from_closing(self):
        with Signed():
            body = (await call("GET", "/compliance/time-bar")).json()
        assert "39(11)" in body["rule"]
        assert "already_barred" in body and "closing_soon" in body


class TestEvidence:
    FILING = {
        "id": "f1", "period": "092026", "return_type": "GSTR1",
        "arn": "AA270926000001X", "filed_at": "2026-10-09T10:00:00Z",
        "filed_by": "owner", "covers_months": ["092026"], "note": None,
        "recorded_at": "2026-10-09T10:05:00Z", "superseded_by": None,
        "payload_json": '{"gstin": "27AAAAA0000A1Z5"}',
    }

    @pytest.mark.anyio
    async def test_lists_what_was_filed(self):
        with Signed(filings=[self.FILING]):
            body = (await call("GET", "/compliance/filings")).json()
        row = body["rows"][0]
        assert row["arn"] == "AA270926000001X"
        assert row["has_payload"] is True
        # The payload itself is fetched on demand: these are whole returns.
        assert "payload_json" not in row

    @pytest.mark.anyio
    async def test_the_payload_is_the_exact_json_submitted(self):
        with Signed():
            with patch("api.routers.compliance.compliance_repository.filing_payload",
                       return_value={"arn": "AA270926000001X", "filed_at": "x",
                                     "period": "092026", "return_type": "GSTR1",
                                     "payload": {"gstin": "27AAAAA0000A1Z5"},
                                     "payload_missing": False}):
                body = (await call("GET", "/compliance/filings/f1/payload")).json()
        assert body["payload"]["gstin"] == "27AAAAA0000A1Z5"

    @pytest.mark.anyio
    async def test_an_unknown_filing_is_a_404(self):
        with Signed():
            with patch("api.routers.compliance.compliance_repository.filing_payload",
                       return_value=None):
                response = await call("GET", "/compliance/filings/nope/payload")
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_a_refusal_is_reported_with_its_reason(self):
        from db.repositories.compliance_repository import ComplianceError
        with Signed(record=ComplianceError("A filing has no evidence without its ARN.")):
            response = await call(
                "POST", "/compliance/filings",
                json={"period": "092026", "return_type": "GSTR1",
                      "arn": "", "filed_at": "2026-10-09T10:00:00Z"},
            )
        assert response.status_code == 422
        assert "ARN" in response.json()["detail"]

    @pytest.mark.anyio
    async def test_the_payload_stored_at_close_is_used_when_none_is_supplied(self):
        # That is what the offline utility was given, so it is what was filed.
        closed = {"status": "CLOSED", "payload_json": '{"gstin": "27AAAAA0000A1Z5"}'}
        with Signed(period_state=closed) as signed:
            await call(
                "POST", "/compliance/filings",
                json={"period": "092026", "return_type": "GSTR1",
                      "arn": "AA270926000001X", "filed_at": "2026-10-09T10:00:00Z"},
            )
        assert signed.recorded["payload"] == {"gstin": "27AAAAA0000A1Z5"}


class TestReminders:
    @pytest.mark.anyio
    async def test_reports_that_they_are_off(self):
        with Signed():
            body = (await call("GET", "/compliance/reminders")).json()
        assert body["settings"]["enabled"] is False
        assert body["due"] == []
        assert "off" in body["note"]

    @pytest.mark.anyio
    async def test_a_preview_shows_the_volume_before_opting_in(self):
        with Signed():
            body = (await call("GET", "/compliance/reminders?preview=true")).json()
        assert body["preview"] is not None

    @pytest.mark.anyio
    async def test_turning_them_on_is_an_explicit_act(self):
        with Signed():
            response = await call(
                "PUT", "/compliance/reminders",
                json={"enabled": True, "days_before": [7, 1]},
            )
        assert response.status_code == 200
        assert response.json()["enabled"] is True
