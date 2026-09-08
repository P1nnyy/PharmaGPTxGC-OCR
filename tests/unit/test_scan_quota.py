"""The trial scan allowance.

Registration is open and every scan bills Azure, so the allowance is what
stops an open sign-up page being a way to spend someone else's OCR budget.
The tests pin the two things that make it real: that it counts something a
user cannot reset, and that completing the shop lifts it.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api import deps
from api.deps import FREE_SCANS_WITHOUT_SHOP, scan_quota, scan_quota_state


def user(**overrides) -> dict:
    base = {"id": "u1", "email": "a@b.com", "role": "super_admin", "pharmacy_id": "ph1"}
    base.update(overrides)
    return base


def with_shop(complete: bool, scans: int):
    return (
        patch.object(deps.pharmacy_repository, "get_profile", return_value={}),
        patch.object(deps.pharmacy_repository, "missing_fields",
                     return_value=[] if complete else ["gstin"]),
        patch.object(deps.scan_repository, "count_scans", return_value=scans),
    )


class TestAllowance:
    def test_the_first_scans_are_allowed(self):
        for used in range(FREE_SCANS_WITHOUT_SHOP):
            a, b, c = with_shop(complete=False, scans=used)
            with a, b, c:
                assert scan_quota(user()) == user()

    def test_the_scan_after_the_allowance_is_refused(self):
        a, b, c = with_shop(complete=False, scans=FREE_SCANS_WITHOUT_SHOP)
        with a, b, c:
            with pytest.raises(HTTPException) as e:
                scan_quota(user())
        assert e.value.status_code == 403
        # The message has to say what would lift it, or it is just a wall.
        assert "Settings" in e.value.detail

    def test_a_completed_shop_lifts_the_limit_entirely(self):
        a, b, c = with_shop(complete=True, scans=999)
        with a, b, c:
            assert scan_quota(user()) == user()

    def test_the_count_comes_from_the_ledger_not_from_invoices(self):
        # Counting invoices would make the quota a formality: delete,
        # re-upload, repeat. The ledger is append-only.
        a, b, c = with_shop(complete=False, scans=FREE_SCANS_WITHOUT_SHOP)
        with a, b, patch.object(deps.scan_repository, "count_scans",
                                return_value=FREE_SCANS_WITHOUT_SHOP) as counted:
            with pytest.raises(HTTPException):
                scan_quota(user())
        assert counted.called


class TestReportedState:
    def test_counts_down_so_the_ui_can_warn_before_the_wall(self):
        a, b, c = with_shop(complete=False, scans=1)
        with a, b, c:
            state = scan_quota_state("ph1")
        assert state["scans_remaining"] == FREE_SCANS_WITHOUT_SHOP - 1
        assert state["unlocked"] is False

    def test_an_unlocked_workspace_reports_no_limit_rather_than_a_big_one(self):
        a, b, c = with_shop(complete=True, scans=40)
        with a, b, c:
            state = scan_quota_state("ph1")
        assert state["unlocked"] is True
        assert state["scan_limit"] is None
        assert state["scans_remaining"] is None

    def test_remaining_never_goes_negative(self):
        a, b, c = with_shop(complete=False, scans=99)
        with a, b, c:
            assert scan_quota_state("ph1")["scans_remaining"] == 0
