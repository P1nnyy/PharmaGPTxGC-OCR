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
