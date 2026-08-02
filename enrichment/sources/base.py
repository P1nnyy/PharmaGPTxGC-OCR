"""What an external reference source is allowed to tell the catalogue.

Everything here is a SUGGESTION. No field on this record is ever written to a
Product without a human accepting it, and the reason is specific rather than
procedural: matching an invoice's abbreviated item name to a public drug
listing is fuzzy, and the fields it would fill are the ones where being wrong
is expensive. DONEP 5MG and DONEP 10MG differ by one token; MAHAFLOX and
MAHAFLOX-LP by one more. An auto-applied mismatch writes the wrong strength
into a medicine record and every stock figure derived from it, silently, at
catalogue scale. That is the exact failure the review queue exists to catch,
so enrichment feeds the queue rather than bypassing it.

Provenance travels with the values: every ProductFacts carries the URL it was
read from and the source that produced it, so a reviewer can check the claim
instead of trusting it.
"""

from typing import Optional, Protocol

from pydantic import BaseModel


class ProductFacts(BaseModel):
    """Catalogue-shaped facts read from one external product listing."""

    source: str
    source_url: str
    # The listing's own name for the product, used to show the reviewer what
    # was actually matched rather than just a score.
    listing_name: Optional[str] = None

    brand: Optional[str] = None
    strength: Optional[str] = None
    form: Optional[str] = None
    pack_size: Optional[str] = None
    pack_multiplier: Optional[int] = None
    base_unit: Optional[str] = None
    manufacturer: Optional[str] = None
    composition: Optional[str] = None

    # Listed consumer price. Never written to the catalogue - MRP belongs to
    # the batch a specific invoice delivered - but shown so a reviewer can
    # sanity-check the match against what they were billed.
    listed_mrp: Optional[float] = None

    # Free-text regulatory note, e.g. "Prescription required". Deliberately
    # NOT mapped to a Schedule: the listings distinguish Rx from OTC but not
    # Schedule H from H1, and guessing between them is a compliance claim
    # nobody checked.
    prescription_note: Optional[str] = None

    # Fields this source could not supply at all, so the UI can say so rather
    # than implying the listing asserted a blank.
    unavailable: list[str] = []

    def filled_fields(self) -> dict:
        """The subset a reviewer could actually apply to a Product."""
        keys = (
            "brand", "strength", "form", "pack_size",
            "pack_multiplier", "base_unit", "manufacturer",
        )
        return {k: getattr(self, k) for k in keys if getattr(self, k) not in (None, "", [])}


class EnrichmentSource(Protocol):
    """A reference site the catalogue can consult.

    Kept behind a protocol so a second source (PharmEasy, a government drug
    registry, a licensed data feed) can be added without the service or the
    review UI changing shape.
    """

    name: str

    def fetch_facts(self, url: str) -> Optional[ProductFacts]:
        ...
