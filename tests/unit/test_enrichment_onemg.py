"""Extraction is pinned against a real captured page state, trimmed to the
branches the extractor actually reads. A synthetic fixture would only prove
the extractor agrees with my assumptions about the payload."""

import json
import os

import pytest

from enrichment.sources.onemg import extract_initial_state, facts_from_state

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "enrichment", "onemg_dulohox_state.json"
)
URL = "https://www.1mg.com/drugs/dulohox-20mg-tablet-732600"


@pytest.fixture
def facts():
    with open(FIXTURE) as f:
        state = json.load(f)
    return facts_from_state(state, URL)


class TestExtraction:
    def test_reads_the_catalogue_fields(self, facts):
        # Upper-cased to match how the catalogue stores brands; the listing
        # itself writes mixed case ("PICOlex"), which would otherwise be
        # written straight into the record.
        assert facts.brand == "DULOHOX"
        assert facts.strength == "20MG"
        assert facts.form == "Tablet"
        assert facts.manufacturer == "Hochest Biotech India"
        assert facts.composition == "Duloxetine (20mg)"

    def test_pack_multiplier_is_the_countable_quantity(self, facts):
        # This is the field that makes tablet-level stock possible.
        assert facts.pack_size == "10 tablets"
        assert facts.pack_multiplier == 10

    def test_base_unit_derived_from_form(self, facts):
        assert facts.base_unit == "TABLET"

    def test_strength_upper_cased_to_match_catalogue(self, facts):
        # Returning "20mg" would read as a difference from the catalogue's
        # "20MG" and make an agreeing source look like a conflicting one.
        assert facts.strength == facts.strength.upper()

    def test_provenance_travels_with_the_values(self, facts):
        assert facts.source == "1mg"
        assert facts.source_url == URL
        assert facts.listing_name == "Dulohox 20mg Tablet"


class TestDeliberateOmissions:
    def test_schedule_and_hsn_are_declared_unavailable(self, facts):
        # Shown to the reviewer as "this source does not publish it", rather
        # than an empty box that looks like the source asserting a blank.
        assert set(facts.unavailable) == {"hsn", "schedule"}

    def test_prescription_status_is_evidence_not_a_schedule(self, facts):
        # Listings distinguish Rx from OTC but not Schedule H from H1, and
        # guessing between them is a compliance claim nobody checked.
        assert facts.prescription_note
        assert "prescription" in facts.prescription_note.lower()
        assert not hasattr(facts, "schedule") or getattr(facts, "schedule", None) is None

    def test_help_link_text_stripped_from_the_note(self, facts):
        assert not facts.prescription_note.endswith("Why?")

    def test_listed_price_captured_but_not_a_catalogue_field(self, facts):
        # For eyeballing the match only - MRP belongs to the batch an invoice
        # delivered, and a second copy here would compete with it.
        assert facts.listed_mrp == 71.0
        assert "listed_mrp" not in facts.filled_fields()


class TestApplicableFields:
    def test_filled_fields_are_the_applicable_subset(self, facts):
        applicable = facts.filled_fields()
        assert applicable["pack_multiplier"] == 10
        assert applicable["manufacturer"] == "Hochest Biotech India"
        for key in ("source", "source_url", "composition", "prescription_note"):
            assert key not in applicable


class TestResilience:
    def test_missing_state_marker_returns_none(self):
        assert extract_initial_state("<html><body>nothing here</body></html>") is None

    def test_unparseable_state_returns_none(self):
        assert extract_initial_state("window.__INITIAL_STATE__ = {broken") is None

    def test_empty_state_yields_no_facts(self):
        assert facts_from_state({}, URL) is None

    def test_missing_branches_degrade_to_nulls_not_exceptions(self):
        # Upstream owns this shape and can change it without notice. One
        # changed key should cost a suggestion, not the review screen.
        facts = facts_from_state({"drugPageReducer": {"staticData": {}, "dynamicData": {}}}, URL)
        assert facts is not None
        assert facts.brand is None and facts.pack_multiplier is None
        assert facts.filled_fields() == {}
