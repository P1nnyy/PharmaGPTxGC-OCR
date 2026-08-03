"""PharmEasy source: JSON-LD extraction and slug parsing.

Pinned against a real captured page, trimmed to the JSON-LD nodes the
extractor reads. Slug cases are real URLs from their sitemap.
"""

import os

import pytest

from enrichment.index import slug_to_fields
from enrichment.sources.pharmeasy import facts_from_html

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "enrichment", "pharmeasy_zolfresh.html"
)
URL = "https://pharmeasy.in/online-medicine-order/zolfresh-5mg-strip-of-15-tablets-864"


@pytest.fixture
def facts():
    with open(FIXTURE) as f:
        return facts_from_html(f.read(), URL)


class TestExtraction:
    def test_reads_the_catalogue_fields(self, facts):
        assert facts.brand == "ZOLFRESH"
        assert facts.strength == "5MG"
        assert facts.form == "Tablet"
        assert facts.manufacturer == "ABBOTT INDIA LTD"

    def test_brand_comes_from_the_brand_node_not_the_title(self, facts):
        # PharmEasy publishes an isolated Brand node, so unlike the 1mg
        # source there is no stripping of strength/form out of a title -
        # and therefore nothing to strip wrongly.
        assert facts.brand == "ZOLFRESH"
        assert "5" not in facts.brand and "TABLET" not in facts.brand

    def test_structured_strength_preferred_over_parsing_text(self, facts):
        # availableStrength gives value and unit separately, so there is no
        # guessing where the number ends. "5.0" normalises to "5MG" to match
        # how the catalogue stores it.
        assert facts.strength == "5MG"

    def test_provenance(self, facts):
        assert facts.source == "PharmEasy"
        assert facts.source_url == URL

    def test_prescription_status_mapped_to_plain_words(self, facts):
        assert facts.prescription_note == "Prescription required"

    def test_schedule_and_hsn_declared_unavailable(self, facts):
        # Same stance as the 1mg source: the listing separates Rx from OTC
        # but not Schedule H from H1, and HSN is not published at all.
        assert set(facts.unavailable) == {"hsn", "schedule"}


class TestCombinationStrengths:
    """PharmEasy states combination doses as parallel plus-separated lists:
    strengthValue "500.0 + 125.0" against strengthUnit "mg+mg". Concatenating
    the raw strings yields "500.0 + 125MG+MG", which is not a dose at all and
    would be written into the catalogue verbatim if a reviewer accepted it."""

    def test_combination_zips_values_with_units(self):
        from enrichment.sources.pharmeasy import _strength_from

        drug = {"availableStrength": {"strengthValue": "500.0 + 125.0", "strengthUnit": "mg+mg"}}
        assert _strength_from(drug) == "500MG+125MG"

    def test_one_unit_covers_every_value(self):
        from enrichment.sources.pharmeasy import _strength_from

        drug = {"availableStrength": {"strengthValue": "5.0 + 10.0", "strengthUnit": "mg"}}
        assert _strength_from(drug) == "5MG+10MG"

    def test_trailing_zero_dropped_but_real_decimals_kept(self):
        from enrichment.sources.pharmeasy import _strength_from

        assert _strength_from({"availableStrength": {"strengthValue": "5.0", "strengthUnit": "mg"}}) == "5MG"
        assert _strength_from({"availableStrength": {"strengthValue": "2.5", "strengthUnit": "mg"}}) == "2.5MG"

    def test_mismatched_shapes_fall_back_rather_than_guess(self):
        # Three values against two units: stitching those together would
        # invent a dose. The ingredient text is used instead.
        from enrichment.sources.pharmeasy import _strength_from

        drug = {
            "availableStrength": {"strengthValue": "1 + 2 + 3", "strengthUnit": "mg+mg"},
            "activeIngredient": "Foo(250.0 Mg)",
        }
        assert _strength_from(drug) == "250MG"


class TestResilience:
    def test_page_without_json_ld_returns_none(self):
        assert facts_from_html("<html><body>nothing</body></html>", URL) is None

    def test_malformed_json_ld_returns_none(self):
        html = '<script type="application/ld+json">{broken</script>'
        assert facts_from_html(html, URL) is None

    def test_json_ld_without_a_product_returns_none(self):
        html = '<script type="application/ld+json">{"@type":"WebSite","name":"x"}</script>'
        assert facts_from_html(html, URL) is None


class TestSlugPack:
    @pytest.mark.parametrize(
        "slug,brand,strength,form,pack,multiplier",
        [
            # The pack the JSON-LD does not carry, free from the URL.
            ("zolfresh-5mg-strip-of-15-tablets-864", "ZOLFRESH", "5MG", "Tablet", "15'S", 15),
            ("tenoclor-50mg-strip-of-15-tablets-567", "TENOCLOR", "50MG", "Tablet", "15'S", 15),
            ("demazole-cream-15gm-1080", "DEMAZOLE", None, "Cream", "15GM", 1),
            ("novorapid-100iu-injection-10ml-729", "NOVORAPID", "100IU", "Injection", "10ML", 1),
        ],
    )
    def test_reads_pack_from_the_url(self, slug, brand, strength, form, pack, multiplier):
        f = slug_to_fields(f"/online-medicine-order/{slug}", "PharmEasy")
        assert f["brand_key"] == brand
        assert f["strength"] == strength
        assert f["form"] == form
        assert f["pack_size"] == pack
        assert f["pack_multiplier"] == multiplier

    def test_a_count_multiplies_but_a_volume_does_not(self):
        # "strip-of-15-tablets" is fifteen dispensable units; "15gm" is one
        # tube holding 15g. Reading either as the other misstates stock by
        # the size of the pack.
        strip = slug_to_fields("/online-medicine-order/x-strip-of-15-tablets-1", "PharmEasy")
        tube = slug_to_fields("/online-medicine-order/x-cream-15gm-2", "PharmEasy")
        assert strip["pack_multiplier"] == 15
        assert tube["pack_multiplier"] == 1

    def test_form_survives_the_pack_pattern_consuming_it(self):
        # "strip-of-15-tablets" swallows the only mention of "tablets", so
        # the form has to be recovered from the pack's own unit or the URL's
        # plain statement of it is lost.
        f = slug_to_fields("/online-medicine-order/zolfresh-5mg-strip-of-15-tablets-864", "PharmEasy")
        assert f["form"] == "Tablet"

    def test_multi_word_form_does_not_leak_into_the_brand(self):
        # "oral-solution" must beat "solution", or "oral" is left behind and
        # the brand indexes as LEVESAM ORAL, which no invoice will spell.
        f = slug_to_fields("/online-medicine-order/levesam-oral-solution-100ml-189", "PharmEasy")
        assert f["brand_key"] == "LEVESAM"

    def test_milligrams_are_a_dose_not_a_pack(self):
        f = slug_to_fields("/online-medicine-order/zytel-ch-80mg-tablet-108", "PharmEasy")
        assert f["strength"] == "80MG"
        assert f["pack_size"] is None


class TestSourceIsolation:
    @pytest.mark.parametrize(
        "slug,brand,strength,form",
        [
            ("/drugs/dulohox-20mg-tablet-732600", "DULOHOX", "20MG", "Tablet"),
            ("/drugs/lipigo-10-tablet-123", "LIPIGO", "10", "Tablet"),
            ("/drugs/eromed-gel-240352", "EROMED", None, "Gel"),
        ],
    )
    def test_pharmeasy_rules_do_not_affect_1mg_slugs(self, slug, brand, strength, form):
        # The pack patterns are PharmEasy-specific; applying them to 1mg
        # slugs would change an index that is already correct.
        f = slug_to_fields(slug, "1mg")
        assert f["brand_key"] == brand
        assert f["strength"] == strength
        assert f["form"] == form
        assert f["pack_size"] is None
