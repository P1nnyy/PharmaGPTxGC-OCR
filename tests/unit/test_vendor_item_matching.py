"""Recognising the same item the second time it is billed.

The rule being tested
---------------------
A distributor's software prints the same string for the same product on every
bill it issues. That makes "this vendor billed this exact description before"
strong enough evidence to act on without asking - which is the whole point of
the cross-reference, and why ERPs have kept one since long before OCR.

What it must not do is treat the NAME as the key. Vendors differ in where they
put things: one spells the pack size inside the item name, the next gives it
its own column. Key on the name alone and

    STERIVON H/S 100 ML   vs   STERIVON H/S 200 ML

become the same item the moment a vendor moves the size out of the name. That
is a confident match onto the wrong SKU, and every stock and rate figure
derived from it is then wrong with no visible symptom. So the key is every
indicator the vendor printed, and a changed indicator asks rather than acts.
"""

import pytest
from unittest.mock import patch

from db.product_repository import (
    ALIAS_MATCH,
    AUTO_CONFIRMED,
    NEEDS_CONFIRMATION,
    NEW_PRODUCT,
    UNSEEN,
    VENDOR_CHANGED,
    VENDOR_EXACT,
    record_vendor_item,
    resolve_line_item_product,
    unlink_vendor_item,
    vendor_item_fingerprint,
    vendor_name_key,
)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def single(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class FakeTx:
    """Serves the cross-reference lookup from a list; records what was written."""

    def __init__(self, vendor_items=None, alias_target=None):
        self.vendor_items = vendor_items or []
        self.alias_target = alias_target
        self.queries = []

    def run(self, query, **params):
        self.queries.append((" ".join(query.split()), params))
        if "s.name_key = $name_key" in query:
            return FakeResult([r for r in self.vendor_items
                               if r["name_key"] == params["name_key"]])
        if "RESOLVES_TO]->(p:Product) RETURN p.id" in " ".join(query.split()):
            return FakeResult([{"product_id": self.alias_target}] if self.alias_target else [])
        if "MERGE (a:ProductAlias" in query:
            return FakeResult([{"alias_id": "alias-1", "product_id": self.alias_target}])
        if "MERGE (p:Product {identity_key" in query:
            return FakeResult([{"id": "product-new"}])
        if "count(*) AS removed" in query:
            return FakeResult([{"removed": 1}])
        return FakeResult([])

    def ran(self, fragment):
        return any(fragment in q for q, _ in self.queries)


def _xref(name_key, fingerprint, product_id="product-1", **extra):
    row = {"name_key": name_key, "fingerprint": fingerprint,
           "product_id": product_id, "pack": "", "manufacturer": "",
           "hsn": "", "times_seen": 3}
    row.update(extra)
    return row


STERIVON = "STERIVON H/S (R.BOTT) 100 ML"


# --------------------------------------------------------------------------
# The fingerprint
# --------------------------------------------------------------------------

def test_same_indicators_give_the_same_fingerprint():
    a = vendor_item_fingerprint(STERIVON, "BOTT", "LEEFORD", "30049099")
    b = vendor_item_fingerprint(STERIVON, "bott", " leeford ", "30049099")
    assert a == b


def test_a_changed_pack_changes_the_fingerprint():
    """The guard against matching 100 ML onto 200 ML."""
    name, _ = vendor_item_fingerprint(STERIVON, "10S", None, None)
    other_name, _ = vendor_item_fingerprint(STERIVON, "15S", None, None)
    _, fp_a = vendor_item_fingerprint(STERIVON, "10S", None, None)
    _, fp_b = vendor_item_fingerprint(STERIVON, "15S", None, None)
    assert name == other_name      # same name...
    assert fp_a != fp_b            # ...but not the same item


def test_vendor_name_key_survives_punctuation_and_case():
    assert vendor_name_key("ARORA BROS MEDI LINKERS") == vendor_name_key("arora bros. medi-linkers")


# --------------------------------------------------------------------------
# Tier 1 - same vendor, everything identical
# --------------------------------------------------------------------------

def test_repeat_from_same_vendor_is_auto_confirmed():
    name_key, fingerprint = vendor_item_fingerprint(STERIVON, "BOTT", "LEEFORD", "30049099")
    tx = FakeTx(vendor_items=[_xref(name_key, fingerprint)])

    match = resolve_line_item_product(tx, "vendor-1", STERIVON, "BOTT", "30049099", "LEEFORD")

    assert match.tier == VENDOR_EXACT
    assert match.status == AUTO_CONFIRMED
    assert match.product_id == "product-1"


def test_auto_confirmed_match_reports_how_often_it_has_been_seen():
    """Feeds the badge: "Auto-matched - 3rd purchase" earns more trust than
    an unexplained value appearing in a field."""
    name_key, fingerprint = vendor_item_fingerprint(STERIVON, None, None, None)
    tx = FakeTx(vendor_items=[_xref(name_key, fingerprint, times_seen=3)])

    match = resolve_line_item_product(tx, "vendor-1", STERIVON)

    assert match.times_seen == 3


def test_a_repeat_does_not_create_a_second_product():
    name_key, fingerprint = vendor_item_fingerprint(STERIVON, None, None, None)
    tx = FakeTx(vendor_items=[_xref(name_key, fingerprint)])

    resolve_line_item_product(tx, "vendor-1", STERIVON)

    assert not tx.ran("MERGE (p:Product {identity_key")


# --------------------------------------------------------------------------
# Tier 2 - same vendor, same name, an indicator moved
# --------------------------------------------------------------------------

def test_changed_pack_from_same_vendor_asks_instead_of_matching():
    name_key, _ = vendor_item_fingerprint(STERIVON, "10S", None, None)
    _, old_fp = vendor_item_fingerprint(STERIVON, "10S", None, None)
    tx = FakeTx(vendor_items=[_xref(name_key, old_fp, pack="10S")])

    match = resolve_line_item_product(tx, "vendor-1", STERIVON, "15S")

    assert match.tier == VENDOR_CHANGED
    assert match.status == NEEDS_CONFIRMATION


def test_the_prompt_names_what_actually_changed():
    """"Confirm this item" is a worse question than "pack 10S became 15S"."""
    name_key, old_fp = vendor_item_fingerprint(STERIVON, "10S", None, None)
    tx = FakeTx(vendor_items=[_xref(name_key, old_fp, pack="10S")])

    match = resolve_line_item_product(tx, "vendor-1", STERIVON, "15S")

    assert "pack" in match.note and "10S" in match.note and "15S" in match.note


def test_changed_manufacturer_is_also_surfaced():
    name_key, old_fp = vendor_item_fingerprint(STERIVON, None, "LEEFORD", None)
    tx = FakeTx(vendor_items=[_xref(name_key, old_fp, manufacturer="LEEFORD")])

    match = resolve_line_item_product(tx, "vendor-1", STERIVON, None, None, "INTAS")

    assert match.status == NEEDS_CONFIRMATION
    assert "manufacturer" in match.note


# --------------------------------------------------------------------------
# Tiers 3 and 4
# --------------------------------------------------------------------------

def test_a_known_spelling_from_a_new_vendor_still_matches():
    """Cross-vendor: the spelling already routes somewhere, so use it."""
    tx = FakeTx(vendor_items=[], alias_target="product-7")

    match = resolve_line_item_product(tx, "vendor-2", STERIVON)

    assert match.tier == ALIAS_MATCH
    assert match.status == AUTO_CONFIRMED


def test_an_unseen_item_is_marked_new_for_review():
    tx = FakeTx(vendor_items=[])

    match = resolve_line_item_product(tx, "vendor-1", "SOMETHING NEVER BILLED 10MG")

    assert match.tier == NEW_PRODUCT
    assert match.status == UNSEEN


def test_no_vendor_still_resolves():
    """Invoices without a readable seller must not lose catalogue resolution."""
    tx = FakeTx(vendor_items=[], alias_target="product-7")

    match = resolve_line_item_product(tx, None, STERIVON)

    assert match.product_id == "product-7"


def test_a_blank_name_matches_nothing():
    tx = FakeTx()
    assert resolve_line_item_product(tx, "vendor-1", "   ").product_id is None


# --------------------------------------------------------------------------
# Writing and undoing the mapping
# --------------------------------------------------------------------------

def test_the_cross_reference_is_written_with_all_indicators():
    tx = FakeTx()
    record_vendor_item(tx, "vendor-1", "product-1", STERIVON, "BOTT", "LEEFORD", "30049099")

    assert tx.ran("MERGE (v)-[s:SUPPLIES {fingerprint: $fingerprint}]->(p)")
    _, params = tx.queries[-1]
    assert params["pack"] == "BOTT" and params["manufacturer"] == "LEEFORD"


def test_nothing_is_written_without_a_vendor():
    """No vendor means no per-vendor claim can be made."""
    tx = FakeTx()
    record_vendor_item(tx, None, "product-1", STERIVON)
    assert not tx.queries


def test_a_mapping_can_be_undone():
    """An automatic action the user cannot reverse is worse than no automation."""
    tx = FakeTx()
    assert unlink_vendor_item(tx, "vendor-1", STERIVON) is True
    assert tx.ran("DELETE s")


def test_binding_never_creates_a_second_route_for_one_spelling():
    """An alias resolving to two Products splits stock and history silently.
    MERGE alone does not prevent it - it only dedupes the edge to the same
    product - so the write is guarded on the alias having no route yet."""
    name_key, fingerprint = vendor_item_fingerprint(STERIVON, None, None, None)
    tx = FakeTx(vendor_items=[_xref(name_key, fingerprint, product_id="product-1")],
                alias_target="product-9")   # spelling already routed elsewhere

    resolve_line_item_product(tx, "vendor-1", STERIVON)

    bind = [q for q, _ in tx.queries if "MERGE (a)-[:RESOLVES_TO]->(p)" in q]
    assert bind, "expected a bind attempt"
    assert "WHERE NOT (a)-[:RESOLVES_TO]->(:Product)" in bind[0]
