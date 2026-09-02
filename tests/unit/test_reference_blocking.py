"""Which reference rows a name is even allowed to be compared against.

Blocking decides what the matcher never sees. A rejection is at least visible
in the candidate list; a name that reaches no candidates at all reports "no
product matches" about a product the index holds, and nothing on the screen
distinguishes that from a genuine absence.
"""

import sqlite3

import pytest

from enrichment import reference_index


@pytest.fixture
def index():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(reference_index.SCHEMA)
    for name in (
        "Lasilactone  50 Tablet",
        "Moxitobra Eye Drop",
        "Omnacortil 10 Tablet DT",
        "Omnacortil 5 Tablet DT",
        "Lasix 40 Tablet",
        "Junior Lanzol 15mg Tablet DT",
        "Lanzol 30 Capsule",
        "Hyponat-O 15 Tablet",
        "Hypon Tablet",
    ):
        connection.execute(
            "INSERT INTO reference_product (brand_name, block, dosage_form) VALUES (?, ?, 'tablet')",
            (name, reference_index.block_key(name)),
        )
    connection.commit()
    yield connection
    connection.close()


def names(rows) -> set:
    return {row["brand_name"] for row in rows}


class TestExactBlocking:
    def test_a_name_reaches_its_own_block(self, index):
        found = names(reference_index.candidates_for("OMNACORTIL 10 MG TAB.", index))
        assert found == {"Omnacortil 10 Tablet DT", "Omnacortil 5 Tablet DT"}

    def test_an_exact_block_is_not_widened(self, index):
        """A name that already found its block must not drag in neighbours."""
        assert "Lasix 40 Tablet" not in names(
            reference_index.candidates_for("OMNACORTIL", index)
        )


class TestNeighbouringBlocks:
    """A first word the invoice truncated or misread found nothing at all.

    This is the case a reference lookup exists to solve, so it cannot be the
    one case that returns an empty list.
    """

    def test_a_truncated_first_word_reaches_the_fuller_one(self, index):
        assert "Lasilactone  50 Tablet" in names(
            reference_index.candidates_for("LASILACTON 50 TAB", index)
        )

    def test_an_abbreviated_first_word_reaches_the_fuller_one(self, index):
        assert "Moxitobra Eye Drop" in names(
            reference_index.candidates_for("MOXITOB E/DROPS", index)
        )

    def test_a_short_opening_is_never_widened(self, index):
        """Below five characters a shared opening says almost nothing, and the
        scan stops being cheap - every three-letter stem opens dozens of
        unrelated brands."""
        assert reference_index.candidates_for("LAS", index) == []

    def test_a_name_with_no_neighbour_still_reports_nothing(self, index):
        assert reference_index.candidates_for("BECOSULE PERFORMANCE", index) == []


class TestBlocksOurOwnFirstWordNeverOpens:
    def test_a_name_the_reference_orders_differently_is_still_reached(self, index):
        """LANZOL JUNIOR 15 is listed as "Junior Lanzol 15mg Tablet DT". Its
        block held only the wrong-strength siblings, so the answer was a
        confident "no product matches"."""
        found = names(reference_index.candidates_for("LANZOL JUNIOR 15", index))
        assert "Junior Lanzol 15mg Tablet DT" in found
        assert "Lanzol 30 Capsule" in found

    def test_a_short_word_does_not_open_a_block_of_its_own(self, index):
        """Below four characters a word is a variant marker, not a name."""
        assert reference_index._query_blocks(["SILODAL", "D"]) == ["SILODAL"]

    def test_only_the_first_few_words_are_looked_up(self, index):
        blocks = reference_index._query_blocks(["ALPHA", "BETA", "GAMMA", "DELTA"])
        assert blocks == ["ALPHA", "BETA", "GAMMA"]

    def test_a_misspelled_block_is_reached(self, index):
        """HYPONET-O is "Hyponat-O" in the reference - one letter apart, which
        the matcher forgives readily once it is given the row."""
        assert "Hyponat-O 15 Tablet" in names(
            reference_index.candidates_for("HYPONET-O 15", index)
        )

    def test_a_useless_neighbour_does_not_hide_the_misspelling(self, index):
        """"Hypon" extends into HYPONET without being related to it. Finding it
        must not end the search."""
        found = names(reference_index.candidates_for("HYPONET-O 15", index))
        assert {"Hypon Tablet", "Hyponat-O 15 Tablet"} <= found

    def test_an_unrelated_block_sharing_an_opening_is_not_reached(self, index):
        assert "Lasix 40 Tablet" not in names(
            reference_index.candidates_for("LASILACTON 50 TAB", index)
        )
