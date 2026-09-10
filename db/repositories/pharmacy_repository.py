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
from core.hsn import policy_digits, policy_for_aato
from core.tenancy import current_tenant
from db.graph_db import get_driver

# How often this shop files GSTR-1. A shop on QRMP files one return per
# quarter; everyone else files monthly. Nothing about an outward return may
# assume monthly — the aggregation window, the filing lock and the documents
# table all follow this, and a quarterly filer aggregated by month would file
# three returns where one was due.
FILING_FREQUENCIES = {"MONTHLY", "QUARTERLY"}

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
    # --- tax identity: what decides the shape of an outward return.
    "filing_frequency",       # MONTHLY or QUARTERLY (QRMP)
    "hsn_digit_policy",       # an explicit override; normally derived from AATO
    "aato_paise",             # declared aggregate turnover, PAN-wide, in paise
    "aato_financial_year",    # the FY start year that declaration covers
    "aato_source",            # where the figure came from, for the audit trail
)

_PUBLIC = WRITABLE_FIELDS + (
    "id", "name", "pan", "state_code", "state", "profile_complete",
)


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

    if "filing_frequency" in clean and clean["filing_frequency"]:
        frequency = str(clean["filing_frequency"]).strip().upper()
        if frequency not in FILING_FREQUENCIES:
            raise ProfileError(
                "Filing frequency is MONTHLY or QUARTERLY. A shop on QRMP files "
                "quarterly."
            )
        clean["filing_frequency"] = frequency

    if "hsn_digit_policy" in clean and clean["hsn_digit_policy"]:
        policy = str(clean["hsn_digit_policy"]).strip().upper()
        if policy not in {"FOUR_DIGIT", "SIX_DIGIT"}:
            raise ProfileError("HSN digit policy is FOUR_DIGIT or SIX_DIGIT.")
        clean["hsn_digit_policy"] = policy

    # Turnover is money, so it is paise and it is an integer. A float here
    # would be a float on the threshold that decides how many HSN digits get
    # filed, which is not a place to lose precision.
    if "aato_paise" in clean and clean["aato_paise"] is not None:
        value = clean["aato_paise"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProfileError("Aggregate turnover must be an integer number of paise.")
        if value < 0:
            raise ProfileError("Aggregate turnover cannot be negative.")

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


def tax_identity(pharmacy_id: Optional[str] = None) -> dict:
    """Everything an outward return needs to know about who is filing it.

    Resolved rather than raw, because two of these are decisions rather than
    stored values and both of them change what gets filed.

    **Filing frequency** defaults to MONTHLY when unset. That is the common
    case and the safe one: a monthly filer aggregated monthly is right, whereas
    defaulting a monthly filer to quarterly would silently merge three months
    into one return. The engine still refuses to close a period when the
    frequency was never set — see the validation report — so this default gets
    a shop as far as *previewing* a return and no further.

    **HSN digits** come from an explicit `hsn_digit_policy` if the shop set
    one, otherwise from declared aggregate turnover. Turnover is *declared*,
    not derived: AATO is PAN-wide across every GSTIN on the PAN, and this
    workspace holds the sales of exactly one of them. Computing it from what we
    can see would understate it for any multi-GSTIN business and quietly file
    four digits where six were owed. So it is asked for, kept with the year it
    covers and where it came from, and cross-checked against our own sales
    rather than replaced by them.
    """
    profile = get_profile(pharmacy_id) or {}
    declared_aato = profile.get("aato_paise")
    policy = profile.get("hsn_digit_policy") or policy_for_aato(declared_aato)
    return {
        "gstin": profile.get("gstin"),
        "pan": profile.get("pan"),
        "state_code": profile.get("state_code"),
        "state": profile.get("state"),
        "legal_name": profile.get("legal_name"),
        "trade_name": profile.get("trade_name"),
        # None, not "MONTHLY", when unset — the caller has to be able to tell
        # "this shop files monthly" from "nobody has said", because only one of
        # those is safe to file on.
        "filing_frequency": profile.get("filing_frequency"),
        "effective_filing_frequency": profile.get("filing_frequency") or "MONTHLY",
        "hsn_digit_policy": policy,
        "hsn_digits": policy_digits(policy),
        "hsn_policy_is_declared": bool(profile.get("hsn_digit_policy")),
        "aato_paise": declared_aato,
        "aato_financial_year": profile.get("aato_financial_year"),
        "aato_source": profile.get("aato_source"),
    }
