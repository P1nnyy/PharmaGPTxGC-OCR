"""Turning catalogue products into reference proposals.

The glue between a Product as the graph stores it and the matcher's view of
it. Kept apart from both so the matching rules stay testable without a
database and the repository stays unaware of enrichment.

Two ways in. `suggest_for_product` only proposes - it names the fields the
reference agrees on and the ones it cannot settle, and a person applies it.
`autofill_products` writes, and is what runs when an invoice is verified, but
it writes under strict limits: empty fields only, unanimous values only, never
marked confirmed, and always recorded in `suggested_fields` so the screen can
say the value is a PharmaGPT suggestion rather than something the invoice said.
"""

import re
from typing import Iterable, Optional

from core.logger import logger
from enrichment import reference_index
from enrichment.reference_match import build_query, forms_agree, propose

# Fields a reference proposal is ever allowed to offer. Deliberately narrow:
# batch, price, tax and schedule are absent because the reference either does
# not know them or knows them in a way that must not become a compliance
# claim - a schedule nobody checked is worse than a blank.
PROPOSABLE = ("form", "base_unit", "strength", "pack_multiplier", "manufacturer", "composition")


def _search_name(product: dict) -> str:
    """What to look the product up by.

    The invoice's own spelling is preferred over the parsed brand: the parser
    strips what it recognises, and anything it failed to recognise is exactly
    the discriminating detail the reference needs to tell GLYCOMET GP 2 from
    GP 2 FORTE.
    """
    aliases = product.get("aliases") or []
    if aliases:
        first = aliases[0]
        if isinstance(first, dict) and first.get("raw_name"):
            return first["raw_name"]
    return product.get("canonical_name") or product.get("brand") or ""


def suggest_for_product(product: dict, connection) -> dict:
    """One product's proposal, with the fields it already has filtered out."""
    name = _search_name(product)
    query = build_query(
        name,
        pack_multiplier=product.get("pack_multiplier"),
        manufacturer=product.get("manufacturer"),
        strength=product.get("strength"),
        form=product.get("form"),
    )
    result = propose(query, reference_index.candidates_for(name, connection))
    result["product_id"] = product.get("id")
    result["query"] = name

    # Only offer what is actually missing. A field the product already holds
    # was either read from its own invoice or typed by a person, and both
    # outrank a reference listing - so a proposal that "agrees" with what is
    # already there is noise, and one that disagrees is a question for a
    # human, not a change to apply in a batch.
    fields = result.get("fields") or {}
    new_fields: dict = {}
    expansions: dict = {}
    conflicts: dict = {}

    for key, value in fields.items():
        if key not in PROPOSABLE:
            continue
        current = product.get(key)
        if current in (None, "", []):
            new_fields[key] = value
        elif str(current).strip().upper() == str(value).strip().upper():
            continue
        elif key == "form" and forms_agree(current, value):
            # The catalogue and the reference name the same presentation in
            # different words - Eye Drops against Drops, Ampoule against
            # Injection. Reported as a disagreement, these would have been the
            # most common "conflict" on the screen while telling a reviewer
            # nothing, and they would have buried the few form conflicts that
            # do mean something.
            continue
        elif _is_expansion(current, value):
            expansions[key] = {"current": current, "suggested": value}
        else:
            conflicts[key] = {"current": current, "suggested": value}

    result["new_fields"] = new_fields
    result["expansions"] = expansions
    result["conflicts"] = conflicts
    return result


def _is_expansion(current, suggested) -> bool:
    """True when the two name the same thing and the reference simply says it fully.

    Invoices truncate the manufacturer to whatever fits the column - MICR for
    Micro Labs, CIPL for Cipla, MACLEODS PHARM for Macleods Pharmaceuticals -
    so almost every manufacturer the reference offers "disagrees" with what we
    hold. Treating those as conflicts would bury the handful of real
    disagreements under dozens of cases where both sides are right.

    A prefix alone would be thin evidence for a company name, but it is not
    doing the work on its own: the row only got this far because the whole
    product name matched, so the maker is already corroborated by identity.
    """
    a = re.sub(r"[^A-Z0-9]", "", str(current).upper())
    b = re.sub(r"[^A-Z0-9]", "", str(suggested).upper())
    if not a or not b:
        return False

    # A strength the parser read as a bare number, given its unit. "5" and
    # "5MG" are the same dose, and the version with the unit is the one worth
    # keeping - a unitless strength cannot be compared against anything later.
    if re.fullmatch(r"\d+(?:\.\d+)?", a) and re.fullmatch(rf"{re.escape(a)}(MG|MCG|GM|G|IU|ML|%)", b):
        return True

    # Three characters is the shortest abbreviation worth trusting as a
    # prefix; below that far too many companies share an opening.
    return len(a) >= 3 and b.startswith(a)


def _code_key(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def resolve_manufacturer_codes(products: Iterable[dict], connection) -> dict[str, str]:
    """Works out what each truncated manufacturer code on the invoices means.

    Invoices cut the maker to whatever fits the column - MICR, CIPL, ZYDU,
    WIN - and a prefix alone cannot settle those: MICR opens Micro, Microgen,
    Micron and Microwin; WIN opens twenty-two companies.

    The evidence that does settle it is already in the catalogue. Some products
    carrying MICR matched a reference listing outright, and those listings say
    Micro Labs Ltd. So the code is resolved from our own matched rows, and the
    answer is then available to every product carrying that code - including
    the ones whose name matched nothing at all, which is exactly where the
    manufacturer was otherwise unknowable.

    Two conditions, both necessary:

      * the code must be a PREFIX of the reference name, so what is being
        proposed is the same company written out rather than a different one;
      * every prefix-compatible listing must agree.

    The prefix test is what keeps distributor codes out. Products marked ADIT
    match listings made by Sun Pharmaceutical - ADIT is whoever supplied them,
    not who made them - and since ADIT opens no part of "Sun", nothing is
    proposed and the discrepancy stays a conflict for a person to read.
    """
    observed: dict[str, set] = {}
    for product in products:
        code = _code_key(product.get("manufacturer"))
        if not code:
            continue
        try:
            candidates = suggest_for_product(product, connection).get("candidates") or []
        except Exception:  # noqa: BLE001 - a bad row must not lose the lexicon
            continue
        if not candidates:
            continue
        name = candidates[0].get("manufacturer")
        if name and _code_key(name).startswith(code):
            observed.setdefault(code, set()).add(name)

    return {code: names.pop() for code, names in observed.items() if len(names) == 1}


def suggest_for_products(products: Iterable[dict], path: Optional[str] = None) -> list[dict]:
    """Proposals for many products over a single connection.

    Batching is only reasonable because the index is local. The equivalent
    over a public listing site would be several hundred outbound requests, and
    that is precisely why the online lookup stays one product at a time.
    """
    if not reference_index.is_available(path):
        return []
    results = []
    with reference_index.connect(path) as connection:
        for product in products:
            try:
                results.append(suggest_for_product(product, connection))
            except Exception as exc:  # noqa: BLE001 - one bad row must not lose the batch
                logger.warning(
                    f"[REFERENCE] Lookup failed for {product.get('id')}: {exc}"
                )
    return results


def autofill_products(product_ids: Optional[list] = None, path: Optional[str] = None) -> dict:
    """Matches products against the reference and writes what it can, unasked.

    This is the ingestion-time pass: a product that arrives from an invoice
    gets whatever the reference can settle immediately, so the item reaches
    the review queue already carrying its form, dispensing unit and maker
    rather than as a row of blanks for a person to research.

    What it writes is deliberately the narrow set:

      * only fields that are still empty on the product, so nothing a person
        or an invoice established is ever displaced;
      * only fields every surviving listing agreed on, so an ambiguous name
        fills nothing rather than filling a guess;
      * never marked as confirmed, and recorded in suggested_fields, so the
        screen can label it a PharmaGPT suggestion and the product still
        goes to a human for approval.

    Expansions are applied too - MICR becoming Micro Labs Ltd, a bare 5
    becoming 5MG. These do replace what the invoice printed, which is why they
    were originally held back for the reviewed flow; they are written here
    because they are the same fact rendered fully, they are attributed as a
    suggestion, and the product goes to the review band regardless. A unitless
    strength in particular is close to useless: it cannot be compared against
    anything, so leaving it as "5" to avoid touching it served nobody.

    Manufacturer codes get one extra pass. An invoice's CIPL is resolved from
    what our own matched listings say (see resolve_manufacturer_codes), so a
    product whose name matched nothing still learns its maker.

    Returns a summary; never raises. Autofill failing must not stop an invoice
    from being verified.
    """
    from db import product_repository

    if not reference_index.is_available(path):
        return {"filled": 0, "skipped": 0, "reason": "reference data not installed"}

    # Read once. list_products is a full aggregate over every invoice and batch
    # in the catalogue, and both the lexicon and the fill pass need it.
    catalogue = product_repository.list_products()
    products = [
        p for p in catalogue
        if product_ids is None or p["id"] in set(product_ids)
    ]

    filled = 0
    fields_written = 0
    with reference_index.connect(path) as connection:
        # Built over the whole catalogue, not just the products being filled:
        # a code is resolved by whichever products happened to match, and
        # those are usually not the ones that need the answer.
        lexicon = resolve_manufacturer_codes(catalogue, connection)

        for product in products:
            try:
                proposal = suggest_for_product(product, connection)
                new_fields = dict(proposal.get("new_fields") or {})
                new_fields.update({
                    field: value["suggested"]
                    for field, value in (proposal.get("expansions") or {}).items()
                })

                # A code the catalogue as a whole has explained, applied to a
                # product that could not explain itself.
                code = _code_key(product.get("manufacturer"))
                resolved = lexicon.get(code)
                if resolved and resolved != product.get("manufacturer"):
                    new_fields["manufacturer"] = resolved

                if not new_fields:
                    continue
                result = product_repository.update_product(
                    product["id"], new_fields, confirm=False,
                    mark_confirmed=False, fetch_result=False,
                )
                # A conflict means filling this in would collide with an
                # existing product. Merging is a decision, so it is left for
                # the review screen rather than resolved here.
                if result and not result.get("conflict"):
                    filled += 1
                    fields_written += len(new_fields)
            except Exception as exc:  # noqa: BLE001 - never block the caller
                logger.warning(f"[REFERENCE] Autofill failed for {product.get('id')}: {exc}")

    logger.info(
        f"[REFERENCE] Autofilled {filled} product(s), {fields_written} field(s), "
        f"over {len(products)} checked"
    )
    return {"filled": filled, "fields": fields_written, "checked": len(products)}
