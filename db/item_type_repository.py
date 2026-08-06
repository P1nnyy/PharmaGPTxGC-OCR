"""Item types: the vocabulary of what a product can BE, and what it is measured in.

Why this moved out of the code
------------------------------
The same list lived in five places, each of which had to be edited together:

    product_parser._FORMS                 30 patterns -> form + unit
    product_parser._SINGLE_CONTAINER_FORMS  18 forms whose pack size is 1
    ProductsPage.FORMS                    27 options in the dropdown
    ProductsPage.BASE_UNITS               10 dispensing units
    the _FORM_TO_UNIT mirror the UI keeps "so the two cannot drift apart"

They had already drifted: the parser knows Rotacap and Suppository, the
dropdown offers 27 of the parser's 30, and the two unit tables are maintained
by hand in two languages. A pharmacy stocking something none of them anticipated
- a device, a surgical consumable, an ayurvedic preparation - had no way to say
so without a code change.

So the vocabulary is data now. The regexes are NOT: reading "SUSP" out of an
OCR'd product name is a parsing rule with real subtlety behind it (CR means
cream in a pack column and controlled-release after a brand name), and it stays
in code where its reasoning is written down. What became editable is the part
that is genuinely a pharmacy's own choice: which item types exist, what units
each is measured in, and whether its pack size is a count or a container.

On deleting built-ins
---------------------
The seeded types can be deactivated but not deleted, because products already
point at them by name. Deleting "Tablet" while four hundred products call
themselves tablets would leave those products referring to a vocabulary entry
that no longer exists - the catalogue equivalent of a dangling foreign key.
Deactivating keeps existing products readable while removing the type from the
pickers, which is what "stop offering this" actually means.
"""

from typing import Any, Optional

from core.logger import logger
from db.graph_db import get_driver

# Units a pharmacy measures things in. Count units describe dispensable items
# ("30 tablets"); measure units describe how much is inside one container
# ("100 ML"). The distinction drives whether pack size means a count or a
# volume, so it is recorded rather than inferred from the unit's name.
COUNT_UNITS = ["TABLET", "CAPSULE", "VIAL", "AMPOULE", "SACHET", "RESPULE", "KIT", "UNIT"]
MEASURE_UNITS = ["ML", "L", "GM", "KG"]
KNOWN_UNITS = COUNT_UNITS + MEASURE_UNITS


# Seeded from what the parser already recognised, so nothing regresses on the
# day this ships: every form the system could previously read still exists,
# with the same base unit and the same pack-size rule.
#
# (name, base_unit, supported_units, single_container)
#
# single_container marks forms sold as one container whose size is a volume or
# a weight rather than a count. A 100ml lotion is one bottle - the 100 says how
# much is inside, not how many there are. Tablets are deliberately not marked:
# a strip holds a genuinely countable number, and defaulting to 1 there would
# understate stock by the size of the strip.
_SEED: list[tuple[str, str, list[str], bool]] = [
    ("Tablet",         "TABLET",  ["TABLET"],       False),
    ("Capsule",        "CAPSULE", ["CAPSULE"],      False),
    ("Injection",      "VIAL",    ["VIAL", "ML"],   False),
    ("Vial",           "VIAL",    ["VIAL", "ML"],   False),
    ("Ampoule",        "AMPOULE", ["AMPOULE", "ML"], False),
    ("Sachet",         "SACHET",  ["SACHET", "GM"], False),
    ("Granules",       "SACHET",  ["SACHET", "GM"], False),
    ("Respule",        "RESPULE", ["RESPULE", "ML"], False),
    ("Rotacap",        "CAPSULE", ["CAPSULE"],      False),
    ("Suppository",    "UNIT",    ["UNIT"],         False),
    ("Kit",            "KIT",     ["KIT"],          False),
    ("Soap",           "UNIT",    ["UNIT", "GM"],   False),
    # Single-container forms: pack size defaults to 1.
    ("Syrup",          "ML",      ["ML"],           True),
    ("Suspension",     "ML",      ["ML"],           True),
    ("Solution",       "ML",      ["ML"],           True),
    ("Drops",          "ML",      ["ML"],           True),
    ("Eye Drops",      "ML",      ["ML"],           True),
    ("Ear Drops",      "ML",      ["ML"],           True),
    ("Eye/Ear Drops",  "ML",      ["ML"],           True),
    ("Nasal Drops",    "ML",      ["ML"],           True),
    ("Nasal Spray",    "ML",      ["ML"],           True),
    ("Spray",          "ML",      ["ML"],           True),
    ("Mouthwash",      "ML",      ["ML"],           True),
    ("Inhaler",        "UNIT",    ["UNIT", "ML"],   True),
    ("Lotion",         "ML",      ["ML", "GM"],     True),
    ("Shampoo",        "ML",      ["ML"],           True),
    # Creams and ointments are sold by weight, but a few are labelled in ml,
    # so both are offered rather than forcing the pharmacist to mislabel one.
    ("Cream",          "GM",      ["GM", "ML"],     True),
    ("Ointment",       "GM",      ["GM", "ML"],     True),
    ("Gel",            "GM",      ["GM", "ML"],     True),
    ("Powder",         "GM",      ["GM"],           True),
]


def _serialize(node) -> dict:
    data = dict(node)
    for key, value in data.items():
        if hasattr(value, "iso_format"):
            data[key] = value.iso_format()
    data.setdefault("supported_units", [])
    data.setdefault("keywords", [])
    return data


def ensure_seeded() -> int:
    """Creates the built-in types once. Safe to call on every boot."""
    driver = get_driver()
    with driver.session() as session:
        created = session.execute_write(_seed_tx)
    if created:
        logger.info(f"[ITEM TYPES] Seeded {created} built-in item type(s)")
    return created


def _seed_tx(tx) -> int:
    created = 0
    for order, (name, base_unit, supported, single) in enumerate(_SEED):
        record = tx.run(
            """
            MERGE (t:ItemType {name: $name})
            ON CREATE SET t.id = randomUUID(),
                          t.base_unit = $base_unit,
                          t.supported_units = $supported,
                          t.single_container = $single,
                          t.keywords = [],
                          t.builtin = true,
                          t.active = true,
                          t.sort_order = $order,
                          t.created_at = datetime()
            RETURN t.created_at IS NOT NULL AS ok, t.id AS id
            """,
            name=name, base_unit=base_unit, supported=supported,
            single=single, order=order,
        ).single()
        if record:
            created += 1
    # Only counts rows touched; the log line above is informational either way.
    return created


def list_item_types(include_inactive: bool = False) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(_list_tx, include_inactive)


def _list_tx(tx, include_inactive: bool) -> list[dict]:
    result = tx.run(
        f"""
        MATCH (t:ItemType)
        {"" if include_inactive else "WHERE coalesce(t.active, true)"}
        RETURN t ORDER BY coalesce(t.sort_order, 999), t.name
        """
    )
    return [_serialize(record["t"]) for record in result]


def create_item_type(fields: dict) -> dict:
    name = str(fields.get("name") or "").strip()
    if not name:
        raise ValueError("An item type needs a name.")

    supported = _clean_units(fields.get("supported_units"))
    base_unit = _clean_unit(fields.get("base_unit")) or (supported[0] if supported else None)
    if not base_unit:
        raise ValueError("An item type needs at least one unit.")
    if base_unit not in supported:
        supported = [base_unit] + supported

    driver = get_driver()
    with driver.session() as session:
        created = session.execute_write(
            _create_tx, name, base_unit, supported,
            bool(fields.get("single_container")),
            _clean_keywords(fields.get("keywords")),
        )
    if created is None:
        raise ValueError(f"An item type named {name!r} already exists.")
    return created


def _create_tx(tx, name, base_unit, supported, single, keywords) -> Optional[dict]:
    exists = tx.run("MATCH (t:ItemType {name: $name}) RETURN t.id AS id", name=name).single()
    if exists:
        return None
    record = tx.run(
        """
        CREATE (t:ItemType {
            id: randomUUID(), name: $name, base_unit: $base_unit,
            supported_units: $supported, single_container: $single,
            keywords: $keywords, builtin: false, active: true,
            sort_order: 500, created_at: datetime()
        })
        RETURN t
        """,
        name=name, base_unit=base_unit, supported=supported,
        single=single, keywords=keywords,
    ).single()
    return _serialize(record["t"])


def update_item_type(type_id: str, fields: dict) -> Optional[dict]:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(_update_tx, type_id, fields)


def _update_tx(tx, type_id: str, fields: dict) -> Optional[dict]:
    existing = tx.run("MATCH (t:ItemType {id: $id}) RETURN t", id=type_id).single()
    if not existing:
        return None
    current = _serialize(existing["t"])

    updates: dict[str, Any] = {}
    if "name" in fields:
        new_name = str(fields["name"] or "").strip()
        if not new_name:
            raise ValueError("An item type needs a name.")
        # Renaming a built-in would strand every product already labelled with
        # the old name, so the name is fixed once products can refer to it.
        if current.get("builtin") and new_name != current.get("name"):
            raise ValueError("A built-in item type cannot be renamed.")
        updates["name"] = new_name
    if "supported_units" in fields:
        updates["supported_units"] = _clean_units(fields["supported_units"])
    if "base_unit" in fields:
        updates["base_unit"] = _clean_unit(fields["base_unit"])
    if "single_container" in fields:
        updates["single_container"] = bool(fields["single_container"])
    if "keywords" in fields:
        updates["keywords"] = _clean_keywords(fields["keywords"])
    if "active" in fields:
        updates["active"] = bool(fields["active"])

    supported = updates.get("supported_units", current.get("supported_units") or [])
    base_unit = updates.get("base_unit", current.get("base_unit"))
    if not supported:
        raise ValueError("An item type needs at least one unit.")
    if base_unit not in supported:
        # The dispensing unit must be one the type actually supports, or the
        # product form would offer a default it then rejects.
        updates["base_unit"] = supported[0]

    set_clause = ", ".join(f"t.{key} = ${key}" for key in updates)
    record = tx.run(
        f"MATCH (t:ItemType {{id: $id}}) SET {set_clause} RETURN t",
        id=type_id, **updates,
    ).single()
    return _serialize(record["t"])


def delete_item_type(type_id: str) -> dict:
    """Removes a custom type, or reports why it cannot go.

    Returns {"deleted": bool, "reason": str|None, "products": int}.
    """
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(_delete_tx, type_id)


def _delete_tx(tx, type_id: str) -> dict:
    record = tx.run("MATCH (t:ItemType {id: $id}) RETURN t", id=type_id).single()
    if not record:
        return {"deleted": False, "reason": "not_found", "products": 0}

    item_type = _serialize(record["t"])
    if item_type.get("builtin"):
        return {"deleted": False, "reason": "builtin", "products": 0}

    in_use = tx.run(
        "MATCH (p:Product {form: $name}) RETURN count(p) AS n",
        name=item_type["name"],
    ).single()["n"]
    if in_use:
        # Deleting it would leave those products naming a vocabulary entry that
        # no longer exists. Deactivating is the honest version of the request.
        return {"deleted": False, "reason": "in_use", "products": in_use}

    tx.run("MATCH (t:ItemType {id: $id}) DETACH DELETE t", id=type_id)
    return {"deleted": True, "reason": None, "products": 0}


# --------------------------------------------------------------------------
# Used by the product write path
# --------------------------------------------------------------------------

def units_for_form(tx, form: Optional[str]) -> Optional[dict]:
    """The unit rules for a form, or None if the form is not in the vocabulary."""
    if not form:
        return None
    record = tx.run(
        """
        MATCH (t:ItemType {name: $name})
        RETURN t.supported_units AS supported_units, t.base_unit AS base_unit,
               coalesce(t.single_container, false) AS single_container
        """,
        name=form,
    ).single()
    return dict(record) if record else None


def _clean_unit(value: Any) -> Optional[str]:
    text = str(value or "").strip().upper()
    return text or None


def _clean_units(values: Any) -> list[str]:
    if not values:
        return []
    seen: list[str] = []
    for value in values:
        unit = _clean_unit(value)
        if unit and unit not in seen:
            seen.append(unit)
    return seen


def _clean_keywords(values: Any) -> list[str]:
    if not values:
        return []
    seen: list[str] = []
    for value in values:
        word = str(value or "").strip().upper()
        if word and word not in seen:
            seen.append(word)
    return seen
