"""Route-level behaviour for the catalogue, with the repository stubbed - what
is under test here is the contract the UI codes against, not Cypher."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.routers.products import (
    AliasSplit,
    ProductMerge,
    ProductUpdate,
    get_product,
    list_products,
    merge_products,
    split_alias,
    update_product,
)


def product(**overrides) -> dict:
    base = {
        "id": "p1",
        "canonical_name": "MONTICOPE SUSPENSION 60 ML",
        "brand": "MONTICOPE",
        "hsn": "30049099",
        "pack_multiplier": 1,
        "review_status": "needs_review",
        "needs_attention": False,
        "flags": [],
        "aliases": [],
    }
    base.update(overrides)
    return base


class TestListing:
    def test_returns_products_and_summary(self):
        with patch("api.routers.products.product_repository.list_products", return_value=[product()]):
            result = list_products()
        assert len(result["products"]) == 1
        assert result["summary"]["total"] == 1
        assert result["summary"]["needs_review"] == 1

    def test_summary_counts_the_whole_catalogue_not_the_filtered_slice(self):
        # The tiles report outstanding work; narrowing a search must not make
        # the backlog appear to shrink.
        catalogue = [
            product(id="p1", canonical_name="MONTICOPE", brand="MONTICOPE", pack_multiplier=None),
            product(id="p2", canonical_name="DONEP", brand="DONEP", pack_multiplier=None),
        ]
        with patch("api.routers.products.product_repository.list_products", return_value=catalogue):
            result = list_products(search="MONTICOPE")
        assert len(result["products"]) == 1
        assert result["summary"]["total"] == 2
        assert result["summary"]["missing_pack_multiplier"] == 2

    def test_status_filter(self):
        catalogue = [
            product(id="p1", review_status="needs_review"),
            product(id="p2", review_status="confirmed"),
        ]
        with patch("api.routers.products.product_repository.list_products", return_value=catalogue):
            assert len(list_products(status="needs_review")["products"]) == 1
            assert len(list_products(status="confirmed")["products"]) == 1
            assert len(list_products()["products"]) == 2

    def test_search_matches_alias_spellings(self):
        # The user searches for what the invoice said, which may not be the
        # canonical name any more.
        catalogue = [product(aliases=[{"raw_name": "MONTICOPE SUSP", "status": "new"}])]
        with patch("api.routers.products.product_repository.list_products", return_value=catalogue):
            assert len(list_products(search="susp")["products"]) == 1

    def test_search_is_case_insensitive(self):
        with patch("api.routers.products.product_repository.list_products", return_value=[product()]):
            assert len(list_products(search="monticope")["products"]) == 1

    def test_price_conflict_counter(self):
        catalogue = [product(flags=[{"code": "mrp_conflict", "severity": "high"}])]
        with patch("api.routers.products.product_repository.list_products", return_value=catalogue):
            assert list_products()["summary"]["price_conflicts"] == 1


class TestGet:
    def test_missing_product_is_404(self):
        with patch("api.routers.products.product_repository.get_product", return_value=None):
            with pytest.raises(HTTPException) as exc:
                get_product("nope")
        assert exc.value.status_code == 404


class TestUpdate:
    def test_only_sent_fields_are_forwarded(self):
        # exclude_unset, not exclude_none - otherwise a field the user
        # deliberately blanked is indistinguishable from one they never
        # touched, and a wrong parser guess could never be cleared.
        payload = ProductUpdate(strength=None, form="Tablet")
        with patch("api.routers.products.product_repository.update_product", return_value=product()) as up:
            update_product("p1", payload)
        _, fields = up.call_args[0]
        assert fields == {"strength": None, "form": "Tablet"}
        assert "confirm" not in fields and "allow_merge" not in fields

    def test_untouched_fields_are_absent(self):
        with patch("api.routers.products.product_repository.update_product", return_value=product()) as up:
            update_product("p1", ProductUpdate(form="Tablet"))
        assert up.call_args[0][1] == {"form": "Tablet"}

    def test_confirm_flag_is_passed_separately(self):
        with patch("api.routers.products.product_repository.update_product", return_value=product()) as up:
            update_product("p1", ProductUpdate(form="Tablet", confirm=True))
        assert up.call_args.kwargs["confirm"] is True

    def test_conflict_is_reported_not_raised(self):
        # Discovering a duplicate is a normal outcome the user resolves, not
        # a failure - and records must never be combined without them asking.
        other = product(id="p2")
        with patch(
            "api.routers.products.product_repository.update_product",
            return_value={"id": "p1", "conflict": other},
        ), patch("api.routers.products.product_repository.get_product", return_value=product()):
            result = update_product("p1", ProductUpdate(strength="10MG"))
        assert result["status"] == "conflict"
        assert result["conflict"]["id"] == "p2"

    def test_missing_product_is_404(self):
        with patch("api.routers.products.product_repository.update_product", return_value=None):
            with pytest.raises(HTTPException) as exc:
                update_product("nope", ProductUpdate(form="Tablet"))
        assert exc.value.status_code == 404


class TestMergeAndSplit:
    def test_merge_forwards_ids(self):
        with patch("api.routers.products.product_repository.merge_products", return_value=product()) as m:
            result = merge_products(ProductMerge(source_ids=["p2", "p3"], target_id="p1"))
        m.assert_called_once_with(["p2", "p3"], "p1")
        assert result["status"] == "ok"

    def test_merge_missing_target_is_404(self):
        with patch("api.routers.products.product_repository.merge_products", return_value=None):
            with pytest.raises(HTTPException) as exc:
                merge_products(ProductMerge(source_ids=["p2"], target_id="gone"))
        assert exc.value.status_code == 404

    def test_split_forwards_only_supplied_overrides(self):
        with patch("api.routers.products.product_repository.split_alias", return_value=product()) as s:
            split_alias("a1", AliasSplit(strength="10MG"))
        s.assert_called_once_with("a1", {"strength": "10MG"})

    def test_split_missing_alias_is_404(self):
        with patch("api.routers.products.product_repository.split_alias", return_value=None):
            with pytest.raises(HTTPException) as exc:
                split_alias("gone", AliasSplit())
        assert exc.value.status_code == 404
