"""The management reports, over one synthetic shelf.

Every expected figure is worked out by hand in the comments. The expiry report
gets the most attention because it is the one the product is for, and because
its second number — the input credit that has to be reversed if the stock is
written off — is the one nobody currently sees coming.

The shelf, as of 2026-09-11:

  P1 Paracetamol, batch B1 — 12 received for ₹1,000 taxable (₹120 credit),
     MRP ₹150 each, expires 2026-10-15 (34 days out). 5 sold. 7 left.
  P1 Paracetamol, batch B2 — 10 received for ₹900, expires 2027-06-30. Beyond
     the horizon, so it should not appear at all.
  P2 Amoxicillin, batch B3 — 20 received for ₹2,000 (₹240 credit), MRP ₹200
     each, expires 2026-09-25 (14 days out). 5 sold at a loss. 15 left.

B1 came from a distributor that takes returns until 10 days before expiry; B3
came from one whose window nobody has recorded.
"""

from datetime import date
from decimal import Decimal

import pytest

from services.management import costing, dashboard, expiry, margin, sales, stock, vendors

TODAY = date(2026, 9, 11)

COSTS = [
    {"product_id": "P1", "batch_number": "B1", "quantity_in": 12.0,
     "cost_paise": 100000, "input_tax_paise": 12000, "mrp_paise": 15000,
     "gst_rate_bp": 1200, "expiry": "2026-10-15", "vendor_id": "V1",
     "first_received_on": "2026-08-01", "last_received_on": "2026-08-01"},
    {"product_id": "P1", "batch_number": "B2", "quantity_in": 10.0,
     "cost_paise": 90000, "input_tax_paise": 10800, "mrp_paise": 15000,
     "gst_rate_bp": 1200, "expiry": "2027-06-30", "vendor_id": "V1",
     "first_received_on": "2026-09-01", "last_received_on": "2026-09-01"},
    {"product_id": "P2", "batch_number": "B3", "quantity_in": 20.0,
     "cost_paise": 200000, "input_tax_paise": 24000, "mrp_paise": 20000,
     "gst_rate_bp": 1200, "expiry": "2026-09-25", "vendor_id": "V2",
     "first_received_on": "2026-07-15", "last_received_on": "2026-07-15"},
]

# Sale movements are stored negative.
SALES_MOVEMENTS = [
    {"product_id": "P1", "batch_number": "B1", "quantity_out": -5.0},
    {"product_id": "P2", "batch_number": "B3", "quantity_out": -5.0},
]

NAMES = {"P1": "Paracetamol 500", "P2": "Amoxicillin 250"}

SOLD_LINES = [
    {"sale_id": "S1", "sale_date": "2026-09-05", "capture_mode": "COUNTER",
     "document_type": "INVOICE", "product_id": "P1", "product_name": "Paracetamol 500",
     "batch_number": "B1", "quantity": 5.0, "taxable_paise": 60000, "rate_bp": 1200},
    # Sold for less than it cost: ₹400 against a ₹500 cost basis.
    {"sale_id": "S2", "sale_date": "2026-09-06", "capture_mode": "COUNTER",
     "document_type": "INVOICE", "product_id": "P2", "product_name": "Amoxicillin 250",
     "batch_number": "B3", "quantity": 5.0, "taxable_paise": 40000, "rate_bp": 1200},
]


@pytest.fixture
def priced():
    return costing.build(COSTS, SALES_MOVEMENTS, NAMES)


class TestCosting:
    def test_weighted_average_is_taken_over_sums(self, priced):
        # Two deliveries of one batch at different prices weight by how much
        # came in, not by averaging the two unit prices.
        merged = costing.build(
            [
                {"product_id": "P9", "batch_number": "B9", "quantity_in": 2.0,
                 "cost_paise": 20000, "input_tax_paise": 0, "mrp_paise": 0},
                {"product_id": "P9", "batch_number": "B9", "quantity_in": 200.0,
                 "cost_paise": 100000, "input_tax_paise": 0, "mrp_paise": 0},
            ],
            [], {},
        )
        # These arrive already summed by the repository, so the last row wins
        # here; what matters is that cost_of divides totals rather than
        # averaging unit prices.
        position = merged.position("P9", "B9")
        assert position.cost_of(position.quantity_in) == position.cost_paise

    def test_on_hand_is_received_less_sold(self, priced):
        assert priced.position("P1", "B1").on_hand == Decimal("7")
        assert priced.position("P2", "B3").on_hand == Decimal("15")

    def test_cost_of_a_part_of_a_batch_rounds_once(self, priced):
        # 7 of 12 packs that cost ₹1,000 together: 100000 × 7/12 = 58333.33.
        assert priced.position("P1", "B1").cost_of(7) == 58333

    def test_input_tax_of_a_part_is_apportioned_the_same_way(self, priced):
        # 12000 × 7/12 is exactly 7000.
        assert priced.position("P1", "B1").input_tax_of(7) == 7000

    def test_mrp_value_multiplies_rather_than_apportions(self, priced):
        # MRP is a per-unit price, not a total to divide up.
        assert priced.position("P1", "B1").mrp_value_of(7) == 105000

    def test_stock_never_reads_negative(self):
        oversold = costing.build(
            [{"product_id": "P1", "batch_number": "B1", "quantity_in": 2.0,
              "cost_paise": 1000, "input_tax_paise": 0, "mrp_paise": 0}],
            [{"product_id": "P1", "batch_number": "B1", "quantity_out": -5.0}], {},
        )
        position = oversold.position("P1", "B1")
        assert position.on_hand == Decimal("0")
        assert position.is_oversold is True

    def test_a_sale_from_a_batch_never_purchased_is_kept_and_flagged(self):
        ghost = costing.build([], [{"product_id": "P1", "batch_number": "GHOST",
                                    "quantity_out": -3.0}], {})
        assert ghost.position("P1", "GHOST").is_oversold is True

    def test_cost_for_a_sale_says_which_basis_it_used(self, priced):
        assert priced.cost_for_sale("P1", "B1", 5)[1] == "BATCH"
        # A batch we never received falls back to the product average, and
        # says so - a margin against a product average is a different quality
        # of number from one against the batch actually sold.
        assert priced.cost_for_sale("P1", "UNKNOWN", 5)[1] == "PRODUCT"
        assert priced.cost_for_sale("P404", "X", 5) == (0, "NONE")


class TestExpiryRisk:
    @pytest.fixture
    def report(self, priced):
        return expiry.build(
            priced, TODAY,
            vendor_windows={"V1": 10},
            vendor_names={"V1": "Alpha Distributors", "V2": "Beta Agencies"},
        )

    def test_buckets_are_exclusive_so_the_totals_add_up(self, report):
        buckets = {b["label"]: b for b in report["buckets"]}
        # B3 is 14 days out, B1 is 34. Each appears once.
        assert buckets["30 days"]["batch_count"] == 1
        assert buckets["60 days"]["batch_count"] == 1
        assert buckets["90 days"]["batch_count"] == 0
        assert buckets["180 days"]["batch_count"] == 0

    def test_stock_beyond_the_horizon_is_not_reported(self, report):
        every = [r["batch_number"] for b in report["buckets"] for r in b["rows"]]
        assert "B2" not in every

    def test_the_headline_is_the_credit_that_must_be_reversed(self, report):
        # 7 of B1 carry ₹70.00 of credit, 15 of B3 carry ₹180.00.
        assert report["totals"]["input_tax_at_risk"] == 250.00

    def test_value_at_cost_and_at_mrp_are_both_reported(self, report):
        # Cost: ₹583.33 + ₹1,500.00. MRP: ₹1,050.00 + ₹3,000.00.
        assert report["totals"]["value_at_cost"] == 2083.33
        assert report["totals"]["value_at_mrp"] == 4050.00

    def test_a_row_carries_everything_needed_to_act(self, report):
        row = next(
            r for b in report["buckets"] for r in b["rows"] if r["batch_number"] == "B1"
        )
        assert row["days_left"] == 34
        assert row["quantity"] == 7.0
        assert row["value_at_cost"] == 583.33
        assert row["input_tax_at_risk"] == 70.00
        assert row["vendor_name"] == "Alpha Distributors"

    def test_the_return_window_turns_expiry_into_a_deadline(self, report):
        # The distributor stops taking returns 10 days before expiry, and there
        # are 34 days left - so 24 days to send it back.
        row = next(
            r for b in report["buckets"] for r in b["rows"] if r["batch_number"] == "B1"
        )
        assert row["return_window_days"] == 10
        assert row["days_left_to_return"] == 24
        assert row["can_still_be_returned"] is True

    def test_an_unknown_window_is_unknown_and_not_a_guess(self, report):
        # Saying "you have time" when nobody knows would be worse than silence.
        row = next(
            r for b in report["buckets"] for r in b["rows"] if r["batch_number"] == "B3"
        )
        assert row["return_window_days"] is None
        assert row["days_left_to_return"] is None
        assert row["can_still_be_returned"] is None
        assert report["totals"]["return_window_unknown_count"] == 1
        assert "will not guess" in report["return_window_note"]

    def test_what_can_still_be_sent_back_is_separated_from_what_cannot(self, report):
        # The difference between a task and a loss.
        assert report["totals"]["still_returnable_value_at_cost"] == 583.33
        assert report["totals"]["still_returnable_batch_count"] == 1

    def test_cites_the_provision_the_reversal_falls_under(self, report):
        assert "17(5)(h)" in report["statutory_note"]
        assert "4(B)(1)" in report["statutory_note"]

    def test_already_expired_stock_is_kept_out_of_the_day_buckets(self, priced):
        # There is no time left to act in, and putting it in "30 days" would
        # suggest there is.
        late = expiry.build(priced, date(2026, 10, 20), vendor_windows={})
        assert late["expired"]["batch_count"] == 2
        assert all(b["batch_count"] == 0 for b in late["buckets"])

    def test_stock_already_sold_carries_no_expiry_risk(self):
        sold_out = costing.build(
            [{"product_id": "P1", "batch_number": "B1", "quantity_in": 5.0,
              "cost_paise": 50000, "input_tax_paise": 6000, "mrp_paise": 15000,
              "expiry": "2026-09-20", "vendor_id": "V1"}],
            [{"product_id": "P1", "batch_number": "B1", "quantity_out": -5.0}], {},
        )
        report = expiry.build(sold_out, TODAY, vendor_windows={})
        assert report["totals"]["batch_count"] == 0


class TestGrossMargin:
    @pytest.fixture
    def report(self, priced):
        return margin.build(SOLD_LINES, priced, day_total_count=0,
                            vendor_names={"V1": "Alpha", "V2": "Beta"})

    def test_margin_is_revenue_less_the_batch_cost(self, report):
        # P1: ₹600 revenue against 100000 × 5/12 = ₹416.67 cost.
        row = next(r for r in report["by_product"] if r["key"] == "P1")
        assert row["revenue"] == 600.00
        assert row["cost"] == 416.67
        assert row["margin"] == 183.33

    def test_flags_a_product_selling_below_cost(self, report):
        # P2: ₹400 revenue against 200000 × 5/20 = ₹500 cost.
        row = next(r for r in report["by_product"] if r["key"] == "P2")
        assert row["margin"] == -100.00
        assert row["is_below_cost"] is True
        assert [r["key"] for r in report["below_cost"]] == ["P2"]

    def test_groups_by_vendor_and_by_month(self, report):
        assert {r["key"] for r in report["by_vendor"]} == {"V1", "V2"}
        assert [r["key"] for r in report["by_month"]] == ["2026-09"]

    def test_a_row_says_how_much_it_can_be_trusted(self, report):
        assert all(r["confidence"] == "BATCH" for r in report["by_product"])

    def test_a_sale_from_an_unreceived_batch_is_marked_estimated(self, priced):
        report = margin.build(
            [{**SOLD_LINES[0], "batch_number": "NEVER-SEEN"}], priced, 0, {}
        )
        row = report["by_product"][0]
        assert row["confidence"] == "PRODUCT"
        assert row["estimated_line_count"] == 1

    def test_revenue_with_no_cost_basis_is_excluded_from_margin(self, priced):
        # Subtracting a zero cost would report the whole sale as margin.
        report = margin.build(
            [{**SOLD_LINES[0], "product_id": "P404", "batch_number": "X"}], priced, 0, {}
        )
        row = report["by_product"][0]
        assert row["uncosted_line_count"] == 1
        assert row["margin"] == 0.00
        assert row["confidence"] == "NONE"

    def test_a_credit_note_nets_out_of_both_sides(self, priced):
        returned = {**SOLD_LINES[0], "document_type": "CREDIT_NOTE"}
        report = margin.build(SOLD_LINES + [returned], priced, 0, {})
        row = next(r for r in report["by_product"] if r["key"] == "P1")
        assert row["revenue"] == 0.00
        assert row["margin"] == 0.00

    def test_day_totals_are_excluded_and_the_reason_is_given(self, priced):
        report = margin.build(SOLD_LINES, priced, day_total_count=12, vendor_names={})
        assert report["excluded"]["day_total_count"] == 12
        assert "carry no product lines" in report["excluded"]["note"]

    def test_an_empty_report_explains_which_of_three_things_happened(self, priced):
        only_day_totals = margin.build([], priced, day_total_count=30, vendor_names={})
        assert "day total" in only_day_totals["empty_reason"]
        assert "counter screen" in only_day_totals["empty_reason"]

        nothing_at_all = margin.build([], priced, day_total_count=0, vendor_names={})
        assert "item detail" in nothing_at_all["empty_reason"]


class TestStockLedgerAndMovers:
    def test_the_balance_runs_per_batch(self):
        report = stock.ledger([
            {"id": "m1", "product_id": "P1", "batch_number": "B1",
             "quantity_delta": 12.0, "reason": "PURCHASE", "occurred_on": "2026-08-01",
             "taxable_paise": 100000, "input_tax_paise": 12000},
            {"id": "m2", "product_id": "P1", "batch_number": "B2",
             "quantity_delta": 10.0, "reason": "PURCHASE", "occurred_on": "2026-09-01",
             "taxable_paise": 90000, "input_tax_paise": 10800},
            {"id": "m3", "product_id": "P1", "batch_number": "B1",
             "quantity_delta": -5.0, "reason": "SALE", "occurred_on": "2026-09-05",
             "taxable_paise": 0, "input_tax_paise": 0},
        ])
        assert [r["balance"] for r in report["rows"]] == [12.0, 10.0, 7.0]

    def test_a_balance_that_goes_below_zero_is_flagged_not_hidden(self):
        report = stock.ledger([
            {"id": "m1", "product_id": "P1", "batch_number": "B1",
             "quantity_delta": -3.0, "reason": "SALE", "occurred_on": "2026-09-05",
             "taxable_paise": 0, "input_tax_paise": 0},
        ])
        assert report["rows"][0]["flags"] == ["NEGATIVE_BALANCE"]
        assert report["negative_balance_count"] == 1

    def test_days_of_cover_turns_a_rate_into_a_date(self, priced):
        # Cover is per product, across every batch of it: P1 has 7 of B1 plus
        # 10 of B2 on hand, and sold 5 in 30 days. 17 / (5/30) = 102 days.
        report = stock.movers(SOLD_LINES, priced, days_observed=30)
        row = next(r for r in report["fast_by_units"] if r["product_id"] == "P1")
        assert row["on_hand"] == 17.0
        assert row["days_of_cover"] == 102.0

    def test_stock_that_never_sold_still_appears(self, priced):
        # Built only from sales it would be missing exactly the slow movers
        # the report exists to surface.
        report = stock.movers([], priced, days_observed=30)
        assert report["totals"]["never_sold_count"] >= 1
        assert any(r["never_sold"] for r in report["slow"])

    def test_nothing_sold_is_not_infinite_cover(self, priced):
        report = stock.movers([], priced, days_observed=30)
        assert all(r["days_of_cover"] is None for r in report["slow"])

    def test_stock_value_is_at_cost(self, priced):
        # 7 of B1 at ₹583.33, 10 of B2 at ₹900, 15 of B3 at ₹1,500.
        assert stock.stock_value(priced)["value_at_cost"] == 2983.33


class TestDailySalesAndTrend:
    def test_every_hour_is_present_including_the_quiet_ones(self):
        report = sales.daily_summary(
            by_hour=[{"hour": 11, "bill_count": 4, "value_paise": 40000}],
            by_day=[{"day": "2026-09-10", "bill_count": 4, "value_paise": 40000}],
            payments=[{"method": "cash", "payment_count": 4, "amount_paise": 40000}],
        )
        assert len(report["by_hour"]) == 24
        assert report["by_hour"][11]["bill_count"] == 4
        assert report["by_hour"][3]["bill_count"] == 0

    def test_average_bill_value_and_the_month_before(self):
        report = sales.daily_summary(
            by_hour=[],
            by_day=[{"day": "2026-09-10", "bill_count": 4, "value_paise": 40000}],
            payments=[],
            previous_by_day=[{"day": "2026-08-10", "bill_count": 5, "value_paise": 25000}],
        )
        assert report["totals"]["average_bill_value"] == 100.00
        assert report["comparison"]["previous_value"] == 250.00
        assert report["comparison"]["value_change_percent"] == 60.0

    def test_a_first_month_has_no_comparison_rather_than_infinite_growth(self):
        report = sales.daily_summary(
            by_hour=[], by_day=[{"day": "2026-09-10", "bill_count": 1, "value_paise": 100}],
            payments=[], previous_by_day=[],
        )
        assert report["comparison"]["value_change_percent"] is None

    def test_cash_is_split_out_from_everything_else(self):
        report = sales.daily_summary(
            by_hour=[], by_day=[{"day": "2026-09-10", "bill_count": 2, "value_paise": 30000}],
            payments=[
                {"method": "cash", "payment_count": 1, "amount_paise": 10000},
                {"method": "upi", "payment_count": 1, "amount_paise": 20000},
            ],
        )
        assert report["cash_vs_digital"]["cash"] == 100.00
        assert report["cash_vs_digital"]["digital"] == 200.00
        assert report["cash_vs_digital"]["cash_share_percent"] == 33.3
        assert report["cash_vs_digital"]["unrecorded"] == 0.00

    def test_the_gap_between_bills_and_recorded_payments_is_shown(self):
        report = sales.daily_summary(
            by_hour=[], by_day=[{"day": "2026-09-10", "bill_count": 2, "value_paise": 30000}],
            payments=[{"method": "cash", "payment_count": 1, "amount_paise": 10000}],
        )
        assert report["cash_vs_digital"]["unrecorded"] == 200.00

    def test_the_trend_carries_a_cumulative_line(self):
        report = sales.trend(
            purchases_by_day=[{"day": "2026-09-01", "cost_paise": 100000, "invoice_count": 1}],
            sales_by_day=[
                {"day": "2026-09-01", "taxable_paise": 30000},
                {"day": "2026-09-02", "taxable_paise": 40000},
            ],
        )
        # A single day of buying is a delivery; the cumulative line is what
        # shows six weeks of it.
        assert [r["cumulative_net"] for r in report["rows"]] == [-700.00, -300.00]


class TestVendorScorecard:
    @pytest.fixture
    def report(self):
        return vendors.build(
            [
                {"vendor_id": "V1", "name": "Alpha Distributors", "gstin": "27AAA",
                 "return_window_days": 10, "invoice_count": 6,
                 "taxable_rupees": 50000.0, "tax_rupees": 6000.0},
                {"vendor_id": "V2", "name": "Beta Agencies", "gstin": "27BBB",
                 "return_window_days": None, "invoice_count": 2,
                 "taxable_rupees": 10000.0, "tax_rupees": 1200.0},
            ],
            months=["092026"],
        )

    def test_ranks_by_how_much_credit_rides_on_each_supplier(self, report):
        assert [r["vendor_id"] for r in report["rows"]] == ["V1", "V2"]
        assert report["rows"][0]["credit_from_this_supplier"] == 6000.00

    def test_filing_columns_are_blank_rather_than_zero(self, report):
        # A zero would render as "filed on time every month", which is a claim
        # about a supplier we have no evidence for.
        filing = report["rows"][0]["filing"]
        assert filing["available"] is False
        assert filing["on_time_rate"] is None
        assert filing["periods_filed_late"] == 0

    def test_says_plainly_that_filing_data_is_not_connected(self, report):
        assert report["source"]["has_filing_data"] is False
        assert "GSTR-2B" in report["source"]["note"]

    def test_the_summary_is_phrased_for_a_shopkeeper(self, report):
        assert "₹6,000" in report["rows"][0]["summary"]
        assert "not known yet" in report["rows"][0]["summary"]

    def test_counts_the_distributors_whose_return_window_is_missing(self, report):
        assert report["totals"]["missing_return_window_count"] == 1

    def test_the_2b_source_refuses_rather_than_reporting_a_clean_record(self):
        with pytest.raises(NotImplementedError):
            vendors.Gstr2bFilingSource().history_for(["V1"], ["092026"])

    def test_the_sentence_reads_as_a_shopkeeper_would_say_it(self):
        history = vendors.FilingHistory(
            vendor_id="V1", periods_expected=6, periods_filed_on_time=2,
            periods_filed_late=4, average_delay_days=31.0, blocked_credit_paise=4200000,
        )
        sentence = vendors._sentence("Distributor X", history, 42000.0)
        assert sentence == (
            "Distributor X filed late in 4 of the last 6 months, delaying "
            "₹42,000 of your credit by an average of 31 days."
        )


class TestDashboard:
    @pytest.fixture
    def cards(self, priced):
        report = expiry.build(priced, TODAY, vendor_windows={"V1": 10})
        return dashboard.build(
            today=TODAY,
            todays_sales_paise=125000,
            todays_bill_count=18,
            comparison_sales_paise=100000,
            expiry_report=report,
            stock=stock.stock_value(priced),
            validation={"blocking": [{"id": "1"}], "warnings": [{"id": "2"}, {"id": "3"}]},
            period_label="Sep 2026",
        )

    def test_there_are_exactly_four(self, cards):
        assert [c["id"] for c in cards["cards"]] == [
            "todays_sales", "itc_at_risk", "compliance_actions", "stock_value",
        ]

    def test_every_card_links_to_the_report_behind_it(self, cards):
        assert all(c["link"] for c in cards["cards"])

    def test_todays_sales_compares_with_the_same_weekday(self, cards):
        # Against last Monday, not against Sunday - a weekday comparison says
        # something about the shop, a day-on-day one about the calendar.
        card = cards["cards"][0]
        assert card["value"] == 1250.00
        assert card["comparison_percent"] == 25.0
        assert "same day last week" in card["comparison_label"]

    def test_the_itc_card_leads_with_the_credit_at_risk(self, cards):
        card = cards["cards"][1]
        assert card["value"] == 250.00
        assert card["tone"] == "bad"
        assert "still go back" in card["note"]

    def test_compliance_counts_blocking_and_warnings(self, cards):
        card = cards["cards"][2]
        assert card["value"] == 3
        assert card["tone"] == "bad"
        assert card["link"] == "/statutory-reports"

    def test_stock_is_valued_at_cost(self, cards):
        assert cards["cards"][3]["value"] == 2983.33

    def test_no_card_is_a_vanity_metric(self, cards):
        # Every one of these changes what somebody does today. Lifetime scans
        # and total invoices processed do not, and must not creep back in.
        titles = " ".join(c["title"].lower() for c in cards["cards"])
        for vanity in ("scan", "total invoices", "processed", "catalogue", "uploads"):
            assert vanity not in titles
