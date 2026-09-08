"""The shop itself - the business behind a workspace.

This is not paperwork for its own sake. The pharmacy's own GSTIN is what lets
a scan tell the two parties on an invoice apart: whichever GSTIN on the bill
matches ours is the buyer, and the other is the seller. Before this, that was
decided by measuring which number sat closer to the vendor's name on the page,
which works until a layout puts them the other way round.

The state code carries the same weight for tax: intra-state purchases split
into CGST and SGST, inter-state ones are IGST, and that is decided by
comparing the seller's state code with ours.
"""

from typing import Any, Optional

from core.gstin import GstinError, parse as parse_gstin
from core.tenancy import current_tenant
from db.graph_db import get_driver

# What a shop must tell us before it can scan. Deliberately short: each of
# these earns its place by changing how an invoice is read or reported, and
# anything that did not was left off the form.
REQUIRED_FIELDS = ("legal_name", "gstin", "address_line1", "city", "pincode")

# Everything a caller may set. Listing them explicitly means a stray key in a
# request body cannot write an arbitrary property onto the node.
WRITABLE_FIELDS = (
    "legal_name",       # as registered for GST
    "trade_name",       # the name over the door, if different
    "gstin",
    "drug_licence_number",   # 20B/21B - a pharmacy cannot trade without one
    "fssai_number",          # only if they stock nutraceuticals
    "address_line1", "address_line2", "city", "pincode",
    "phone", "contact_email",
)

_PUBLIC = WRITABLE_FIELDS + ("id", "name", "pan", "state_code", "state", "profile_complete")


class ProfileError(ValueError):
    """Raised when a shop profile cannot be accepted."""


def _serialize(node) -> Optional[dict]:
    if node is None:
        return None
    data = dict(node)
    out = {}
    for key in _PUBLIC:
        v = data.get(key)
        out[key] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


def get_profile(pharmacy_id: Optional[str] = None) -> Optional[dict]:
    driver = get_driver()
    with driver.session() as session:
        rows = session.execute_read(
            lambda tx: [r for r in tx.run(
                "MATCH (ph:Pharmacy {id: $id}) RETURN ph", id=pharmacy_id or current_tenant())]
        )
    return _serialize(rows[0]["ph"]) if rows else None


def update_profile(fields: dict[str, Any], pharmacy_id: Optional[str] = None) -> dict:
    """Applies the fields given, validating the ones that carry meaning.

    The GSTIN is validated rather than stored as typed, and the PAN and state
    are derived from it instead of being asked for separately - the number
    already contains both, and asking twice invites them to disagree.
    """
    workspace = pharmacy_id or current_tenant()

    clean: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in WRITABLE_FIELDS or value is None:
            continue
        clean[key] = value.strip() if isinstance(value, str) else value

    if "gstin" in clean and clean["gstin"]:
        try:
            parsed = parse_gstin(clean["gstin"])
        except GstinError as e:
            raise ProfileError(str(e))
        clean["gstin"] = parsed["gstin"]
        clean["pan"] = parsed["pan"]
        clean["state_code"] = parsed["state_code"]
        clean["state"] = parsed["state"]

    if "pincode" in clean and clean["pincode"]:
        pin = str(clean["pincode"]).strip()
        if not (pin.isdigit() and len(pin) == 6):
            raise ProfileError("An Indian PIN code is six digits.")
        clean["pincode"] = pin

    if not clean:
        existing = get_profile(workspace)
        if existing is None:
            raise ProfileError("That workspace no longer exists.")
        return existing

    # The shop's display name follows its trade name, falling back to the
    # legal one, so the workspace is not still called "Someone's pharmacy"
    # after the real details are filled in.
    sets = ", ".join(f"ph.{k} = ${k}" for k in clean)
    driver = get_driver()
    with driver.session() as session:
        record = session.execute_write(
            lambda tx: tx.run(
                f"""
                MATCH (ph:Pharmacy {{id: $id}})
                SET {sets}
                SET ph.name = coalesce(ph.trade_name, ph.legal_name, ph.name)
                SET ph.profile_complete = ({
                    ' AND '.join(f'ph.{f} IS NOT NULL' for f in REQUIRED_FIELDS)
                })
                RETURN ph
                """,
                id=workspace, **clean,
            ).single()
        )
    if record is None:
        raise ProfileError("That workspace no longer exists.")
    return _serialize(record["ph"])


def missing_fields(profile: Optional[dict]) -> list[str]:
    """Which required details are still absent. Drives the setup prompt."""
    if not profile:
        return list(REQUIRED_FIELDS)
    return [f for f in REQUIRED_FIELDS if not profile.get(f)]


def own_gstin(pharmacy_id: Optional[str] = None) -> Optional[str]:
    """This workspace's GSTIN, for telling buyer from seller on a scan."""
    profile = get_profile(pharmacy_id)
    return (profile or {}).get("gstin")
