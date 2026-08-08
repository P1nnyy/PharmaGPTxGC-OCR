"""The catalogue's vocabulary, once it became data instead of five code lists.

What this protects
------------------
The item type is what a product IS, and it carries the units that product can
be measured in. Getting the unit wrong is not a cosmetic problem: a cream
recorded in TABLET produces stock figures that are confidently, invisibly
wrong, and nothing downstream can tell that from a real count. So the type's
unit list is enforced on the product rather than merely suggested by the UI.

The other half is about not stranding data. Built-in types can be switched off
but never deleted or renamed, and a custom type in use cannot be deleted,
because products refer to their type by name - removing one would leave those
products naming a vocabulary entry that no longer exists.
"""

import pytest

from db import item_type_repository
from db.item_type_repository import (
    COUNT_UNITS,
    KNOWN_UNITS,
    MEASURE_UNITS,
    _SEED,
    _clean_units,
    _create_tx,
    _delete_tx,
    _update_tx,
)
from db.product_repository import _apply_item_type_rules


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def single(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class FakeTx:
    """Answers the item-type lookups from a dict of name -> rules."""

    def __init__(self, types=None, products_using=0, existing=None):
        self.types = types or {}
        self.products_using = products_using
        self.existing = existing
        self.queries = []

    def run(self, query, **params):
        flat = " ".join(query.split())
        self.queries.append((flat, params))
        if "RETURN t.supported_units AS supported_units" in flat:
            rules = self.types.get(params.get("name"))
            return FakeResult([rules] if rules else [])
        if "MATCH (t:ItemType {id: $id}) RETURN t" in flat:
            return FakeResult([{"t": self.existing}] if self.existing else [])
        if "MATCH (t:ItemType {name: $name}) RETURN t.id" in flat:
            return FakeResult([{"id": "existing"}] if self.existing else [])
        if "count(p) AS n" in flat:
            return FakeResult([{"n": self.products_using}])
        if "CREATE (t:ItemType" in flat or "SET" in flat and "RETURN t" in flat:
            merged = dict(self.existing or {})
            merged.update({k: v for k, v in params.items() if k != "id"})
            return FakeResult([{"t": merged}])
        return FakeResult([])


# --------------------------------------------------------------------------
# The seeded vocabulary
# --------------------------------------------------------------------------

def test_every_seeded_type_uses_a_known_unit():
    for name, base_unit, supported, _ in _SEED:
        assert base_unit in KNOWN_UNITS, f"{name} has an unknown base unit {base_unit}"
        for unit in supported:
            assert unit in KNOWN_UNITS, f"{name} supports unknown unit {unit}"


def test_every_seeded_base_unit_is_one_of_its_supported_units():
    """Otherwise the picker offers a default the product form then rejects."""
    for name, base_unit, supported, _ in _SEED:
        assert base_unit in supported, f"{name} defaults to a unit it does not support"


def test_tablets_are_not_single_container():
    """A strip holds a countable number; defaulting its pack size to 1 would
    understate stock by the size of the strip."""
    by_name = {name: single for name, _, _, single in _SEED}
    assert by_name["Tablet"] is False
    assert by_name["Capsule"] is False


def test_liquids_and_creams_are_single_container():
    """A 100ml lotion is one bottle - the 100 says how much is inside."""
    by_name = {name: single for name, _, _, single in _SEED}
    for form in ("Lotion", "Cream", "Syrup", "Ointment", "Powder", "Gel"):
        assert by_name[form] is True, f"{form} should default its pack size to 1"


def test_units_are_split_into_counts_and_measures():
    """Pack size means a count for one group and a quantity for the other."""
    assert set(COUNT_UNITS).isdisjoint(MEASURE_UNITS)
    assert "TABLET" in COUNT_UNITS and "ML" in MEASURE_UNITS


def test_unit_input_is_normalised():
    assert _clean_units([" ml ", "GM", "ml", ""]) == ["ML", "GM"]


# --------------------------------------------------------------------------
# The rules binding on a product
# --------------------------------------------------------------------------

CREAM = {"supported_units": ["GM", "ML"], "base_unit": "GM", "single_container": True}


def test_a_unit_the_type_does_not_support_is_refused():
    tx = FakeTx(types={"Cream": CREAM})
    with pytest.raises(ValueError, match="TABLET is not one of them"):
        _apply_item_type_rules(tx, {"base_unit": "TABLET"}, {"form": "Cream", "base_unit": "TABLET"})


def test_the_refusal_says_how_to_allow_it():
    """The admin can legitimately want that unit; the message says where."""
    tx = FakeTx(types={"Cream": CREAM})
    with pytest.raises(ValueError, match="Settings"):
        _apply_item_type_rules(tx, {"base_unit": "TABLET"}, {"form": "Cream", "base_unit": "TABLET"})


def test_a_supported_unit_passes():
    tx = FakeTx(types={"Cream": CREAM})
    updates = {"base_unit": "ML"}
    _apply_item_type_rules(tx, updates, {"form": "Cream", "base_unit": "ML"})
    assert updates["base_unit"] == "ML"


def test_changing_form_adopts_the_new_type_unit():
    """Switching Tablet -> Cream must not leave TABLET behind."""
    tx = FakeTx(types={"Cream": CREAM})
    updates = {"form": "Cream"}
    merged = {"form": "Cream", "base_unit": "TABLET"}
    _apply_item_type_rules(tx, updates, merged)
    assert updates["base_unit"] == "GM"


def test_a_form_with_no_item_type_is_left_alone():
    """Types can be switched off while products still carry the name; refusing
    to save those products would strand them."""
    tx = FakeTx(types={})
    updates = {"base_unit": "ANYTHING"}
    _apply_item_type_rules(tx, updates, {"form": "Retired Form", "base_unit": "ANYTHING"})
    assert updates["base_unit"] == "ANYTHING"


def test_a_product_with_no_form_is_left_alone():
    tx = FakeTx(types={"Cream": CREAM})
    updates = {"base_unit": "ML"}
    _apply_item_type_rules(tx, updates, {"form": None, "base_unit": "ML"})
    assert updates["base_unit"] == "ML"


# --------------------------------------------------------------------------
# Not stranding products that point at a type
# --------------------------------------------------------------------------

def test_a_builtin_type_cannot_be_deleted():
    tx = FakeTx(existing={"id": "t1", "name": "Tablet", "builtin": True})
    result = _delete_tx(tx, "t1")
    assert result["deleted"] is False
    assert result["reason"] == "builtin"


def test_a_custom_type_in_use_cannot_be_deleted():
    tx = FakeTx(existing={"id": "t2", "name": "Device", "builtin": False}, products_using=12)
    result = _delete_tx(tx, "t2")
    assert result["deleted"] is False
    assert result["reason"] == "in_use"
    assert result["products"] == 12


def test_an_unused_custom_type_can_be_deleted():
    tx = FakeTx(existing={"id": "t3", "name": "Device", "builtin": False}, products_using=0)
    assert _delete_tx(tx, "t3")["deleted"] is True


def test_a_builtin_cannot_be_renamed():
    """Products name their type; renaming would strand every one of them."""
    tx = FakeTx(existing={"id": "t1", "name": "Tablet", "builtin": True,
                          "supported_units": ["TABLET"], "base_unit": "TABLET"})
    with pytest.raises(ValueError, match="cannot be renamed"):
        _update_tx(tx, "t1", {"name": "Pill"})


def test_a_builtin_can_still_be_switched_off():
    """Deactivating is what "stop offering this" actually means."""
    tx = FakeTx(existing={"id": "t1", "name": "Tablet", "builtin": True,
                          "supported_units": ["TABLET"], "base_unit": "TABLET"})
    result = _update_tx(tx, "t1", {"active": False})
    assert result["active"] is False


def test_a_type_cannot_be_left_with_no_units():
    tx = FakeTx(existing={"id": "t1", "name": "Cream", "builtin": False,
                          "supported_units": ["GM"], "base_unit": "GM"})
    with pytest.raises(ValueError, match="at least one unit"):
        _update_tx(tx, "t1", {"supported_units": []})


def test_a_base_unit_outside_the_supported_list_is_corrected():
    tx = FakeTx(existing={"id": "t1", "name": "Cream", "builtin": False,
                          "supported_units": ["GM", "ML"], "base_unit": "GM"})
    result = _update_tx(tx, "t1", {"supported_units": ["ML"]})
    assert result["base_unit"] == "ML"


def test_creating_a_type_without_a_name_is_refused():
    with pytest.raises(ValueError, match="needs a name"):
        item_type_repository.create_item_type({"name": "  ", "supported_units": ["ML"]})


def test_creating_a_type_without_units_is_refused():
    with pytest.raises(ValueError, match="at least one unit"):
        item_type_repository.create_item_type({"name": "Device", "supported_units": []})


def test_a_duplicate_name_is_refused():
    tx = FakeTx(existing={"id": "t1", "name": "Device"})
    assert _create_tx(tx, "Device", "UNIT", ["UNIT"], False, []) is None


# --------------------------------------------------------------------------
# The HTTP surface
# --------------------------------------------------------------------------

from unittest.mock import patch

from fastapi import HTTPException

import api.routers.item_types as routes
import api.routers.products as product_routes


def test_list_returns_the_vocabulary_and_the_unit_families():
    """The UI needs the unit list to render the picker, so it ships with the
    types rather than being hardcoded a second time in the frontend."""
    with patch("api.routers.item_types.item_type_repository.list_item_types", return_value=[]):
        payload = routes.list_item_types()

    assert payload["known_units"] == KNOWN_UNITS
    assert payload["count_units"] and payload["measure_units"]


def test_deleting_a_builtin_answers_409_and_names_the_alternative():
    with patch("api.routers.item_types.item_type_repository.delete_item_type",
               return_value={"deleted": False, "reason": "builtin", "products": 0}):
        with pytest.raises(HTTPException) as exc:
            routes.delete_item_type("t1")

    assert exc.value.status_code == 409
    assert "switch it off" in exc.value.detail.lower()


def test_deleting_a_type_in_use_says_how_many_products_block_it():
    with patch("api.routers.item_types.item_type_repository.delete_item_type",
               return_value={"deleted": False, "reason": "in_use", "products": 12}):
        with pytest.raises(HTTPException) as exc:
            routes.delete_item_type("t2")

    assert exc.value.status_code == 409
    assert "12 product" in exc.value.detail


def test_deleting_a_missing_type_is_404_not_409():
    with patch("api.routers.item_types.item_type_repository.delete_item_type",
               return_value={"deleted": False, "reason": "not_found", "products": 0}):
        with pytest.raises(HTTPException) as exc:
            routes.delete_item_type("nope")

    assert exc.value.status_code == 404


def test_an_invalid_definition_is_400_with_the_reason():
    with patch("api.routers.item_types.item_type_repository.create_item_type",
               side_effect=ValueError("An item type needs a name.")):
        with pytest.raises(HTTPException) as exc:
            routes.create_item_type(routes.ItemTypeCreate(name="x", supported_units=[]))

    assert exc.value.status_code == 400
    assert "needs a name" in exc.value.detail


def test_a_rejected_product_unit_reaches_the_client_as_400():
    """The message names the type's own units and where to change them, so it
    has to survive the route rather than becoming a generic 500."""
    message = "Cream is measured in GM, ML — TABLET is not one of them."
    with patch("api.routers.products.product_repository.update_product", side_effect=ValueError(message)):
        with pytest.raises(HTTPException) as exc:
            product_routes.update_product("p1", product_routes.ProductUpdate(base_unit="TABLET"))

    assert exc.value.status_code == 400
    assert exc.value.detail == message
