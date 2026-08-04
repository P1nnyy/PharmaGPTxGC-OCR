"""Service-level tests for the report composers.

The repository is stubbed throughout: these tests are about how rows are shaped
into a report, not about Cypher. Repository behaviour is exercised against a
real graph, not here.
"""

from datetime import date
from unittest.mock import patch

import pytest

from services.reports import expiry, gst, overview, procurement, quality
from services.reports.periods import resolve

PERIOD = resolve(kind="fy", fy=2026)
VERIFIED = ["verified"]


def _register_row(**overrides):
    row = {
        "invoice_id": "inv-1",
        "invoice_date": "2026-08-03",
        "invoice_number": "GST-15168",
        "seller_name": "Arora Bros Medi Linkers",
        "seller_gstin": "07AABCU9603R1ZM",
        "taxable_value": 2000.0,
        "discount": 0.0,
        "cgst": 60.0,
        "sgst": 60.0,
        "igst": None,
        "roundoff": None,
        "grand_total": 2120.0,
        "status": "verified",
    }
    row.update(overrides)
    return row


class TestGstRegister:
    def test_totals_claimable_tax_for_invoices_with_a_gstin(self):
        with patch("db.repositories.reports_repository.gst_register", return_value=[_register_row()]):
            result = gst.register(PERIOD, VERIFIED)

        assert result["claimable_tax"] == 120.0
        assert result["blocked_tax"] == 0.0
        assert result["rows"][0]["itc_eligible"] is True

    def test_a_missing_gstin_blocks_the_credit(self):
        """The whole point of the report: no supplier GSTIN, no input credit."""
        with patch(
            "db.repositories.reports_repository.gst_register",
            return_value=[_register_row(seller_gstin=None)],
        ):
            result = gst.register(PERIOD, VERIFIED)

        assert result["claimable_tax"] == 0.0
        assert result["blocked_tax"] == 120.0
        assert result["blocked_invoice_count"] == 1
        assert result["rows"][0]["itc_blocked_reason"] == "Supplier GSTIN missing"

    def test_supply_type_comes_from_the_tax_heads_present(self):
        rows = [
            _register_row(invoice_id="a"),
            _register_row(invoice_id="b", cgst=None, sgst=None, igst=120.0),
        ]
        with patch("db.repositories.reports_repository.gst_register", return_value=rows):
            result = gst.register(PERIOD, VERIFIED)

        assert [r["supply_type"] for r in result["rows"]] == ["intra_state", "inter_state"]

    def test_an_invoice_with_no_tax_captured_is_not_counted_as_claimable(self):
        with patch(
            "db.repositories.reports_repository.gst_register",
            return_value=[_register_row(cgst=None, sgst=None, igst=None)],
        ):
            result = gst.register(PERIOD, VERIFIED)

        assert result["claimable_tax"] == 0.0
        assert result["rows"][0]["tax_total"] is None
        assert result["rows"][0]["itc_eligible"] is False


class TestHsnSummary:
    def test_groups_value_by_slab(self):
        rows = [
            {"hsn": "3004", "gst_percent": 12.0, "line_count": 3, "taxable_value": 900.0,
             "quantity": 30, "batch_count": 3},
            {"hsn": "3005", "gst_percent": 5.0, "line_count": 1, "taxable_value": 100.0,
             "quantity": 10, "batch_count": 1},
        ]
        with patch("db.repositories.reports_repository.hsn_summary", return_value=rows):
            result = gst.hsn_summary(PERIOD, VERIFIED)

        assert result["taxable_total"] == 1000.0
        by_slab = {s["gst_percent"]: s for s in result["slabs"]}
        assert by_slab[12.0]["taxable_value"] == 900.0
        assert by_slab[12.0]["share"] == pytest.approx(0.9)

    def test_one_hsn_under_two_slabs_is_flagged_as_a_conflict(self):
        """An HSN determines its slab, so two slabs means a misread rate."""
        rows = [
            {"hsn": "3004", "gst_percent": 12.0, "line_count": 1, "taxable_value": 500.0,
             "quantity": 5, "batch_count": 1},
            {"hsn": "3004", "gst_percent": 5.0, "line_count": 1, "taxable_value": 500.0,
             "quantity": 5, "batch_count": 1},
        ]
        with patch("db.repositories.reports_repository.hsn_summary", return_value=rows):
            result = gst.hsn_summary(PERIOD, VERIFIED)

        assert result["slab_conflicts"] == [{"hsn": "3004", "slabs": [5.0, 12.0]}]

    def test_an_unexpected_slab_is_marked(self):
        rows = [{"hsn": "3004", "gst_percent": 7.5, "line_count": 1, "taxable_value": 100.0,
                 "quantity": 1, "batch_count": 1}]
        with patch("db.repositories.reports_repository.hsn_summary", return_value=rows):
            result = gst.hsn_summary(PERIOD, VERIFIED)

        assert result["rows"][0]["slab_is_expected"] is False


def _batch_row(**overrides):
    row = {
        "expiry_date": "2026-09-30",
        "batch_number": "B123",
        "product_name": "Amoxycillin 500",
        "pack": "10x10",
        "quantity": 10.0,
        "free_quantity": 1.0,
        "rate": 100.0,
        "mrp": 140.0,
        "amount": 950.0,
        "gst_percent": 12.0,
        "invoice_id": "inv-1",
        "invoice_number": "GST-1",
        "invoice_date": "2026-08-03",
        "vendor_name": "Arora Bros",
    }
    row.update(overrides)
    return row


class TestExpiryExposure:
    AS_OF = date(2026, 8, 5)

    def test_buckets_by_time_remaining_and_values_at_cost(self):
        with patch(
            "db.repositories.reports_repository.expiring_batches",
            return_value=[_batch_row()],
        ):
            result = expiry.build(VERIFIED, as_of=self.AS_OF)

        bucket = next(b for b in result["buckets"] if b["bucket"] == "31_60")
        assert bucket["batch_count"] == 1
        assert bucket["value_at_risk"] == 950.0
        assert result["total_value_at_risk"] == 950.0

    def test_stock_beyond_the_horizon_is_excluded_from_the_headline(self):
        rows = [_batch_row(expiry_date="2026-09-30"), _batch_row(expiry_date="2028-01-31")]
        with patch("db.repositories.reports_repository.expiring_batches", return_value=rows):
            result = expiry.build(VERIFIED, as_of=self.AS_OF, horizon_days=180)

        assert result["total_value_at_risk"] == 950.0
        assert len(result["rows"]) == 1

    def test_already_expired_stock_is_counted_as_actionable(self):
        with patch(
            "db.repositories.reports_repository.expiring_batches",
            return_value=[_batch_row(expiry_date="2026-07-31")],
        ):
            result = expiry.build(VERIFIED, as_of=self.AS_OF)

        assert result["actionable_value"] == 950.0
        assert result["rows"][0]["days_remaining"] < 0

    def test_rows_are_ordered_most_urgent_first(self):
        rows = [
            _batch_row(expiry_date="2026-11-30", batch_number="later"),
            _batch_row(expiry_date="2026-08-31", batch_number="sooner"),
        ]
        with patch("db.repositories.reports_repository.expiring_batches", return_value=rows):
            result = expiry.build(VERIFIED, as_of=self.AS_OF)

        assert [r["batch_number"] for r in result["rows"]] == ["sooner", "later"]

    def test_a_missing_amount_falls_back_to_rate_times_quantity(self):
        """Valuing it at zero would hide the batch from the report entirely."""
        with patch(
            "db.repositories.reports_repository.expiring_batches",
            return_value=[_batch_row(amount=None)],
        ):
            result = expiry.build(VERIFIED, as_of=self.AS_OF)

        assert result["total_value_at_risk"] == 1000.0

    def test_an_unreadable_expiry_is_counted_not_dropped(self):
        with patch(
            "db.repositories.reports_repository.expiring_batches",
            return_value=[_batch_row(expiry_date="08/26")],
        ):
            result = expiry.build(VERIFIED, as_of=self.AS_OF)

        assert result["batches_with_unreadable_expiry"] == 1
        assert result["total_value_at_risk"] == 0.0

    def test_payload_states_that_values_are_purchased_not_on_hand(self):
        """Without sales data the figure is an upper bound, and must say so."""
        with patch("db.repositories.reports_repository.expiring_batches", return_value=[]):
            result = expiry.build(VERIFIED, as_of=self.AS_OF)

        assert result["basis"] == "quantity_purchased"
        assert "upper bound" in result["basis_note"]


class TestVendorScorecard:
    def test_computes_share_and_effective_discount(self):
        rows = [
            {
                "vendor_name": "Arora Bros", "gstin": "07AABCU9603R1ZM", "invoice_count": 2,
                "gross_total": 3000.0, "taxable_total": 2700.0, "line_total": 2700.0,
                "list_value_total": 3000.0, "billed_units": 100.0, "free_units": 10.0,
                "line_discount": 300.0, "last_purchase_date": "2026-08-03",
            },
            {
                "vendor_name": "Medico", "gstin": "07AAACM1234R1ZQ", "invoice_count": 1,
                "gross_total": 1000.0, "taxable_total": 900.0, "line_total": 900.0,
                "list_value_total": 1000.0, "billed_units": 50.0, "free_units": 0.0,
                "line_discount": 100.0, "last_purchase_date": "2026-07-11",
            },
        ]
        with patch("db.repositories.reports_repository.vendor_breakdown", return_value=rows):
            result = procurement.vendor_scorecard(PERIOD, VERIFIED)

        assert result["total_spend"] == 4000.0
        arora = result["vendors"][0]
        assert arora["share"] == pytest.approx(0.75)
        assert arora["effective_discount_rate"] == pytest.approx(0.10)
        assert arora["free_unit_share"] == pytest.approx(10 / 110)

    def test_an_unidentified_supplier_is_counted(self):
        rows = [{
            "vendor_name": "Unidentified supplier", "gstin": None, "invoice_count": 1,
            "gross_total": 500.0, "taxable_total": 500.0, "line_total": 500.0,
            "list_value_total": 500.0, "billed_units": 5.0, "free_units": 0.0,
            "line_discount": 0.0, "last_purchase_date": "2026-05-01",
        }]
        with patch("db.repositories.reports_repository.vendor_breakdown", return_value=rows):
            result = procurement.vendor_scorecard(PERIOD, VERIFIED)

        assert result["unidentified_vendor_count"] == 1
        assert result["vendors"][0]["identified"] is False


def _purchase(product_id="p1", **overrides):
    row = {
        "product_id": product_id,
        "product_name": "Amoxycillin 500",
        "pack": "10x10",
        "rate": 100.0,
        "mrp": 140.0,
        "quantity": 10.0,
        "free_quantity": 0.0,
        "amount": 1000.0,
        "gst_percent": 12.0,
        "invoice_date": "2026-05-01",
        "invoice_id": "inv-1",
        "invoice_number": "GST-1",
        "vendor_name": "Arora Bros",
    }
    row.update(overrides)
    return row


class TestPriceVariance:
    def test_detects_a_rate_increase_across_purchases(self):
        rows = [
            _purchase(invoice_date="2026-05-01", amount=1000.0),
            _purchase(invoice_date="2026-07-01", amount=1200.0, invoice_id="inv-2"),
        ]
        with patch("db.repositories.reports_repository.product_purchase_history", return_value=rows):
            result = procurement.price_variance(PERIOD, VERIFIED)

        product = result["products"][0]
        assert product["rate_change"] == pytest.approx(0.20)
        assert product["rate_increased"] is True
        assert result["increased_count"] == 1

    def test_a_single_purchase_yields_no_variance_signal(self):
        """One data point is not a trend, and flagging it produces noise."""
        with patch(
            "db.repositories.reports_repository.product_purchase_history",
            return_value=[_purchase()],
        ):
            result = procurement.price_variance(PERIOD, VERIFIED)

        assert result["products"][0]["rate_change"] is None
        assert result["increased_count"] == 0

    def test_cross_vendor_spread_only_appears_with_two_suppliers(self):
        rows = [
            _purchase(vendor_name="Arora Bros", amount=1000.0),
            _purchase(vendor_name="Medico", amount=900.0, invoice_id="inv-2",
                      invoice_date="2026-06-01"),
        ]
        with patch("db.repositories.reports_repository.product_purchase_history", return_value=rows):
            result = procurement.price_variance(PERIOD, VERIFIED)

        product = result["products"][0]
        assert product["cross_vendor_spread"] == pytest.approx(10.0)
        assert product["cheapest_vendor"] == "Medico"
        assert result["multi_vendor_count"] == 1

    def test_same_vendor_price_change_is_not_a_sourcing_opportunity(self):
        rows = [
            _purchase(amount=1000.0),
            _purchase(amount=900.0, invoice_id="inv-2", invoice_date="2026-06-01"),
        ]
        with patch("db.repositories.reports_repository.product_purchase_history", return_value=rows):
            result = procurement.price_variance(PERIOD, VERIFIED)

        assert result["products"][0]["cross_vendor_spread"] is None

    def test_free_goods_lower_the_effective_cost(self):
        with patch(
            "db.repositories.reports_repository.product_purchase_history",
            return_value=[_purchase(quantity=10.0, free_quantity=1.0, amount=1000.0)],
        ):
            result = procurement.price_variance(PERIOD, VERIFIED)

        assert result["products"][0]["latest_unit_cost"] == pytest.approx(90.9091, abs=1e-4)

    def test_margin_is_blank_when_the_gst_slab_is_unknown(self):
        with patch(
            "db.repositories.reports_repository.product_purchase_history",
            return_value=[_purchase(gst_percent=None)],
        ):
            result = procurement.price_variance(PERIOD, VERIFIED)

        assert result["products"][0]["latest_margin"] is None


class TestDataQuality:
    def _patched(self, rows, undated=None, duplicates=None):
        return (
            patch("db.repositories.reports_repository.data_quality_rows", return_value=rows),
            patch("db.repositories.reports_repository.undated_invoices", return_value=undated or []),
            patch("db.repositories.reports_repository.duplicate_candidates", return_value=duplicates or []),
        )

    def _run(self, rows, undated=None, duplicates=None):
        a, b, c = self._patched(rows, undated, duplicates)
        with a, b, c:
            return quality.build(PERIOD)

    def test_missing_gstin_is_blocking_and_quantified(self):
        rows = [{
            "invoice_id": "inv-1", "invoice_number": "GST-1", "invoice_date": "2026-08-03",
            "seller_name": "Arora", "seller_gstin": None, "subtotal": 1000.0, "discount": 0.0,
            "cgst": 60.0, "sgst": 60.0, "igst": None, "roundoff": None, "grand_total": 1120.0,
            "status": "verified", "confidence": 0.9, "line_total": 1000.0,
            "line_count": 2, "estimated_lines": 0,
        }]
        result = self._run(rows)

        issue = next(i for i in result["issues"] if i["code"] == "missing_seller_gstin")
        assert issue["severity"] == "blocking"
        assert issue["value_at_stake"] == 120.0
        assert result["itc_at_risk"] == 120.0

    def test_an_invoice_that_does_not_add_up_is_flagged(self):
        rows = [{
            "invoice_id": "inv-1", "invoice_number": "GST-1", "invoice_date": "2026-08-03",
            "seller_name": "Arora", "seller_gstin": "07AABCU9603R1ZM", "subtotal": 1000.0,
            "discount": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "roundoff": None,
            "grand_total": 5000.0, "status": "verified", "confidence": 0.9,
            "line_total": 1000.0, "line_count": 2, "estimated_lines": 0,
        }]
        result = self._run(rows)

        issue = next(i for i in result["issues"] if i["code"] == "arithmetic_mismatch")
        assert issue["value_at_stake"] == 4000.0

    def test_an_undated_invoice_is_reported_as_missing_from_every_period(self):
        undated = [{
            "invoice_id": "inv-9", "invoice_number": "GST-9", "seller_name": "Medico",
            "grand_total": 700.0, "status": "needs_review",
        }]
        result = self._run([], undated=undated)

        issue = next(i for i in result["issues"] if i["code"] == "unreadable_date")
        assert issue["severity"] == "blocking"

    def test_duplicate_exposure_counts_every_copy_beyond_the_first(self):
        duplicates = [{
            "gstin": "07AABCU9603R1ZM", "invoice_number": "GST-1", "occurrence_count": 2,
            "invoices": [
                {"invoice_id": "a", "grand_total": 2000.0, "status": "verified",
                 "invoice_date": "2026-08-03", "seller_name": "Arora"},
                {"invoice_id": "b", "grand_total": 2000.0, "status": "verified",
                 "invoice_date": "2026-08-03", "seller_name": "Arora"},
            ],
        }]
        result = self._run([], duplicates=duplicates)

        issue = next(i for i in result["issues"] if i["code"] == "possible_duplicate")
        assert issue["value_at_stake"] == 2000.0
        assert result["duplicate_group_count"] == 1

    def test_blocking_issues_sort_above_warnings(self):
        rows = [{
            "invoice_id": "inv-1", "invoice_number": "GST-1", "invoice_date": "2026-08-03",
            "seller_name": "Arora", "seller_gstin": None, "subtotal": 1000.0, "discount": 0.0,
            "cgst": 60.0, "sgst": 60.0, "igst": None, "roundoff": None, "grand_total": 5000.0,
            "status": "verified", "confidence": 0.9, "line_total": 1000.0,
            "line_count": 2, "estimated_lines": 1,
        }]
        result = self._run(rows)

        severities = [i["severity"] for i in result["issues"]]
        assert severities == sorted(severities, key=lambda s: {"blocking": 0, "warning": 1, "info": 2}[s])


class TestOverview:
    def test_reports_what_the_status_filter_excluded(self):
        summary = {
            "included": {
                "invoice_count": 3, "gross_total": 3000.0, "taxable_total": 2700.0,
                "discount_total": 100.0, "cgst_total": 150.0, "sgst_total": 150.0,
                "igst_total": 0.0, "line_total": 2700.0, "list_value_total": 3000.0,
                "estimated_line_count": 1, "vendor_count": 2,
            },
            "excluded": {"invoice_count": 2, "gross_total": 840.0},
        }
        with patch("db.repositories.reports_repository.period_summary", return_value=summary):
            result = overview.build(PERIOD, VERIFIED)

        assert result["tax_total"] == 300.0
        assert result["excluded"]["invoice_count"] == 2
        assert result["excluded"]["gross_total"] == 840.0

    def test_empty_months_are_kept_as_zero_in_the_trend(self):
        """A month with no purchases is information; dropping it lets the
        neighbouring months close ranks and hides the gap."""
        with patch(
            "db.repositories.reports_repository.monthly_spend",
            return_value=[{"month": "2026-08", "gross_total": 2278.0,
                           "taxable_total": 2000.0, "invoice_count": 1}],
        ):
            result = overview.spend_trend(PERIOD, VERIFIED)

        assert len(result["series"]) == 12
        assert result["series"][0]["month"] == "2026-04"
        assert result["series"][0]["gross_total"] == 0.0
        assert result["peak_month"] == "2026-08"

    def test_average_uses_active_months_only(self):
        """Averaging over the whole FY understates the run rate for a pharmacy
        that only started uploading partway through."""
        with patch(
            "db.repositories.reports_repository.monthly_spend",
            return_value=[
                {"month": "2026-08", "gross_total": 1000.0, "taxable_total": 900.0, "invoice_count": 1},
                {"month": "2026-09", "gross_total": 2000.0, "taxable_total": 1800.0, "invoice_count": 2},
            ],
        ):
            result = overview.spend_trend(PERIOD, VERIFIED)

        assert result["active_month_count"] == 2
        assert result["average_active_month"] == 1500.0

    def test_an_empty_period_yields_no_average_rather_than_zero(self):
        with patch("db.repositories.reports_repository.monthly_spend", return_value=[]):
            result = overview.spend_trend(PERIOD, VERIFIED)

        assert result["average_active_month"] is None
        assert result["peak_month"] is None
