"""The one reference path that writes without anybody asking.

Everything else in the reference layer proposes and waits for a click. This
runs when an invoice is verified, so its limits are the whole safety story:
it fills and it expands, but it never resolves a disagreement, never claims a
person approved anything, and always says the value came from the reference.
"""

from unittest.mock import patch

import pytest

from enrichment import reference_service


def product(**overrides) -> dict:
    base = {
        "id": "p1",
        "canonical_name": "TRIOLMESAR 20 15'S",
        "brand": "TRIOLMESAR",
        "aliases": [{"id": "a1", "raw_name": "TRIOLMESAR 20 15'S"}],
        "strength": None, "form": None, "pack_size": "15'S",
        "pack_multiplier": 15, "base_unit": None, "manufacturer": "MACLEODS PHARM",
    }
    base.update(overrides)
    return base


def proposal(**overrides) -> dict:
    base = {
        "status": "ok",
        "new_fields": {"form": "Tablet", "base_unit": "TABLET", "strength": "20MG"},
        "expansions": {"manufacturer": {"current": "MACLEODS PHARM",
                                        "suggested": "Macleods Pharmaceuticals Pvt Ltd"}},
        "conflicts": {"pack_multiplier": {"current": 15, "suggested": 10}},
        "candidates": [{"manufacturer": "Macleods Pharmaceuticals Pvt Ltd"}],
    }
    base.update(overrides)
    return base


def run(products, proposals, update_result=None):
    """Drives autofill with the graph and the index stubbed out."""
    with patch.object(reference_service.reference_index, "is_available", return_value=True), \
         patch.object(reference_service.reference_index, "connect"), \
         patch("db.product_repository.list_products", return_value=products), \
         patch.object(reference_service, "suggest_for_product",
                      side_effect=lambda p, _c: proposals[p["id"]]), \
         patch("db.product_repository.update_product",
               return_value=update_result or {"id": "p1"}) as update:
        summary = reference_service.autofill_products()
    return summary, update


class TestWhatItWrites:
    def test_fills_empty_fields(self):
        summary, update = run([product()], {"p1": proposal()})
        assert summary["filled"] == 1
        written = update.call_args.args[1]
        assert written["form"] == "Tablet"
        assert written["strength"] == "20MG"

    def test_applies_expansions_too(self):
        # The same fact written out fully. A unitless strength especially:
        # "5" cannot be compared against anything, so declining to touch it
        # served nobody.
        _, update = run([product()], {"p1": proposal()})
        assert update.call_args.args[1]["manufacturer"] == "Macleods Pharmaceuticals Pvt Ltd"

    def test_never_writes_a_conflict(self):
        # The invoice says a pack of 15 and the reference says 10. One of them
        # is wrong and only a person can say which.
        _, update = run([product()], {"p1": proposal()})
        assert update.call_args.args[1].get("pack_multiplier") != 10

    def test_writes_without_confirming_and_without_claiming_a_reading(self):
        _, update = run([product()], {"p1": proposal()})
        assert update.call_args.kwargs["confirm"] is False
        assert update.call_args.kwargs["mark_confirmed"] is False

    def test_a_proposal_with_nothing_to_say_writes_nothing(self):
        empty = proposal(new_fields={}, expansions={}, conflicts={}, candidates=[])
        summary, update = run([product(manufacturer=None)], {"p1": empty})
        assert summary["filled"] == 0
        update.assert_not_called()


class TestManufacturerCodes:
    """A code is resolved by the products that matched, and applied to those
    that did not - which is the only way a product whose name matches nothing
    ever learns its maker."""

    def test_a_code_learned_elsewhere_reaches_an_unmatched_product(self):
        matched = product(id="p1", manufacturer="CIPL")
        unmatched = product(id="p2", manufacturer="CIPL", canonical_name="HYPERNEB 3%")
        proposals = {
            "p1": proposal(new_fields={}, expansions={}, conflicts={},
                           candidates=[{"manufacturer": "Cipla Ltd"}]),
            # No candidates at all: this name matched nothing.
            "p2": proposal(new_fields={}, expansions={}, conflicts={}, candidates=[]),
        }
        _, update = run([matched, unmatched], proposals, update_result={"id": "p2"})
        written = [c.args[1] for c in update.call_args_list]
        assert {"manufacturer": "Cipla Ltd"} in written

    def test_a_distributor_code_is_never_mistaken_for_the_maker(self):
        # Products marked ADIT match listings made by Sun Pharmaceutical. ADIT
        # is who supplied them, not who made them, and it opens no part of
        # "Sun" - so nothing is proposed and the discrepancy stays a conflict.
        p = product(id="p1", manufacturer="ADIT")
        proposals = {"p1": proposal(new_fields={}, expansions={}, conflicts={},
                                    candidates=[{"manufacturer": "Sun Pharmaceutical Industries Ltd"}])}
        _, update = run([p], proposals)
        update.assert_not_called()

    def test_codes_that_disagree_resolve_to_nothing(self):
        a = product(id="p1", manufacturer="MICR")
        b = product(id="p2", manufacturer="MICR")
        proposals = {
            "p1": proposal(new_fields={}, expansions={}, conflicts={},
                           candidates=[{"manufacturer": "Micro Labs Ltd"}]),
            "p2": proposal(new_fields={}, expansions={}, conflicts={},
                           candidates=[{"manufacturer": "Microgen Health Care"}]),
        }
        _, update = run([a, b], proposals)
        update.assert_not_called()


class TestResilience:
    def test_one_bad_product_does_not_lose_the_run(self):
        good, bad = product(id="good"), product(id="bad")

        def flaky(p, _c):
            if p["id"] == "bad":
                raise RuntimeError("boom")
            return proposal()

        with patch.object(reference_service.reference_index, "is_available", return_value=True), \
             patch.object(reference_service.reference_index, "connect"), \
             patch("db.product_repository.list_products", return_value=[bad, good]), \
             patch.object(reference_service, "suggest_for_product", side_effect=flaky), \
             patch("db.product_repository.update_product", return_value={"id": "good"}):
            summary = reference_service.autofill_products()
        assert summary["filled"] == 1
        assert summary["checked"] == 2

    def test_a_fill_that_would_collide_is_left_for_a_person(self):
        summary, _ = run([product()], {"p1": proposal()},
                         update_result={"id": "p1", "conflict": {"canonical_name": "Other"}})
        assert summary["filled"] == 0

    def test_a_missing_index_is_reported_not_raised(self):
        # Verifying an invoice must never fail because reference data is absent.
        with patch.object(reference_service.reference_index, "is_available", return_value=False):
            summary = reference_service.autofill_products()
        assert summary["filled"] == 0
        assert "not installed" in summary["reason"]


class TestEquivalentFormsAreNotConflicts:
    """The catalogue and the reference name the same presentation differently.

    Reported as disagreements these would be the most common conflict on the
    screen while telling a reviewer nothing, and they would bury the few form
    conflicts that do mean something.
    """

    def _suggest(self, current_form, proposed_form):
        with patch.object(reference_service.reference_index, "candidates_for", return_value=[]), \
             patch.object(reference_service, "propose",
                          return_value={"status": "ok", "fields": {"form": proposed_form}}):
            return reference_service.suggest_for_product(
                product(form=current_form), connection=None
            )

    @pytest.mark.parametrize(
        "current_form, proposed_form",
        [("Eye Drops", "Drops"), ("Ampoule", "Injection"), ("Syrup", "Suspension"),
         ("Respule", "Respules")],
    )
    def test_the_same_presentation_named_differently_is_not_offered(
        self, current_form, proposed_form
    ):
        result = self._suggest(current_form, proposed_form)
        assert result["conflicts"] == {}
        assert "form" not in result["new_fields"]

    def test_a_genuinely_different_form_is_still_a_conflict(self):
        assert "form" in self._suggest("Capsule", "Tablet")["conflicts"]
