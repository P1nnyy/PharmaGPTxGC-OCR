from typing import Optional

from neo4j import GraphDatabase, Driver

from core.config import settings
from core.logger import logger

_driver: Optional[Driver] = None

CONSTRAINTS = [
    "CREATE CONSTRAINT pharmacy_id IF NOT EXISTS FOR (n:Pharmacy) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (n:User) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT user_email IF NOT EXISTS FOR (n:User) REQUIRE n.email IS UNIQUE",
    "CREATE CONSTRAINT invoice_id IF NOT EXISTS FOR (n:Invoice) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT lineitem_id IF NOT EXISTS FOR (n:LineItem) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT vendor_id IF NOT EXISTS FOR (n:Vendor) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT vendor_gstin IF NOT EXISTS FOR (n:Vendor) REQUIRE n.gstin IS UNIQUE",
    "CREATE CONSTRAINT product_id IF NOT EXISTS FOR (n:Product) REQUIRE n.id IS UNIQUE",
    # Product identity is the SKU (brand + strength + form + pack), not the
    # spelling an invoice happened to print. The spelling lives on
    # ProductAlias, which is what many-to-one merging hangs off.
    "CREATE CONSTRAINT product_identity IF NOT EXISTS FOR (n:Product) REQUIRE n.identity_key IS UNIQUE",
    "CREATE CONSTRAINT product_alias_id IF NOT EXISTS FOR (n:ProductAlias) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT product_alias_key IF NOT EXISTS FOR (n:ProductAlias) REQUIRE n.normalized_name IS UNIQUE",
    # Batch uniqueness is enforced at the application level via a deterministic
    # id (product_id + "::" + batch_number) rather than a composite NODE KEY,
    # since composite constraints require an Aura tier that may not be available.
    "CREATE CONSTRAINT batch_id IF NOT EXISTS FOR (n:Batch) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT hsn_code IF NOT EXISTS FOR (n:HSNCode) REQUIRE n.code IS UNIQUE",
    # Products refer to their item type by name, so two types sharing one name
    # would make a product's form ambiguous.
    "CREATE CONSTRAINT item_type_id IF NOT EXISTS FOR (n:ItemType) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT item_type_name IF NOT EXISTS FOR (n:ItemType) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT invitation_id IF NOT EXISTS FOR (n:Invitation) REQUIRE n.id IS UNIQUE",
    # The token is the credential, so it must resolve to at most one invitation.
    "CREATE CONSTRAINT invitation_token IF NOT EXISTS FOR (n:Invitation) REQUIRE n.token IS UNIQUE",
    "CREATE CONSTRAINT audit_event_id IF NOT EXISTS FOR (n:AuditEvent) REQUIRE n.id IS UNIQUE",
    # The audit trail is always read as "this workspace, newest first", so the
    # workspace is indexed; without it every read scans every tenant's events.
    "CREATE INDEX audit_event_scope IF NOT EXISTS FOR (n:AuditEvent) ON (n.pharmacy_id)",
    # The scan ledger. Append-only and never deleted, so that "how many scans
    # have I run" does not fall when an invoice is tidied away.
    "CREATE CONSTRAINT scan_event_id IF NOT EXISTS FOR (n:ScanEvent) REQUIRE n.id IS UNIQUE",
    # Sales. The dedupe key is the one that matters: it is what makes ingesting
    # the same day total, bill photo or imported row twice a no-op instead of a
    # second declaration of the same output tax. Enforced by the database and
    # not only by the MERGE, because two concurrent requests can both find no
    # existing node and both create one.
    "CREATE CONSTRAINT sale_id IF NOT EXISTS FOR (n:Sale) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT sale_dedupe_key IF NOT EXISTS FOR (n:Sale) REQUIRE n.dedupe_key IS UNIQUE",
    # Sales are always read as "this workspace, this period", so both are
    # indexed; without them every read scans every tenant's sales.
    "CREATE INDEX sale_scope IF NOT EXISTS FOR (n:Sale) ON (n.pharmacy_id)",
    "CREATE INDEX sale_period IF NOT EXISTS FOR (n:Sale) ON (n.tax_period)",
    "CREATE CONSTRAINT sale_rate_block_id IF NOT EXISTS FOR (n:SaleRateBlock) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT sale_payment_id IF NOT EXISTS FOR (n:SalePayment) REQUIRE n.id IS UNIQUE",
    # The filing lock. Keyed on a deterministic "<pharmacy>::<MMYYYY>" string
    # rather than a composite constraint, matching how Batch does it, since
    # composite keys need an Aura tier that may not be available.
    "CREATE CONSTRAINT tax_period_key IF NOT EXISTS FOR (n:TaxPeriod) REQUIRE n.key IS UNIQUE",
    # A remembered import column mapping, per workspace and format.
    "CREATE CONSTRAINT import_mapping_key IF NOT EXISTS FOR (n:ImportMapping) REQUIRE n.key IS UNIQUE",
    # A scanned barcode bound to a product. Keyed "<pharmacy>::<code>" so one
    # workspace's binding cannot resolve on another's counter.
    "CREATE CONSTRAINT product_code_key IF NOT EXISTS FOR (n:ProductCode) REQUIRE n.key IS UNIQUE",
    # The serial counter a device's block is cut from. The uniqueness
    # constraint is what makes MERGE take a write lock, and that lock is the
    # only thing standing between two devices and the same invoice number.
    "CREATE CONSTRAINT serial_series_key IF NOT EXISTS FOR (n:SerialSeries) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT serial_block_id IF NOT EXISTS FOR (n:SerialBlock) REQUIRE n.id IS UNIQUE",
    # Stock movements are an append-only ledger; a sale writes rows here and
    # never edits one.
    "CREATE CONSTRAINT stock_movement_id IF NOT EXISTS FOR (n:StockMovement) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX stock_movement_scope IF NOT EXISTS FOR (n:StockMovement) ON (n.pharmacy_id)",
    "CREATE CONSTRAINT sale_line_id IF NOT EXISTS FOR (n:SaleLine) REQUIRE n.id IS UNIQUE",
]

# Constraints from an earlier schema that are actively wrong now. product_key
# made the invoice's spelling of a name the product's identity, which is the
# collision this catalogue layer exists to undo - two renderings of one SKU
# could never merge while it stood.
STALE_CONSTRAINTS = [
    "DROP CONSTRAINT product_key IF EXISTS",
]


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        if not settings.NEO4J_URI or not settings.NEO4J_USERNAME or not settings.NEO4J_PASSWORD:
            raise ValueError(
                "Neo4j is not configured. Set NEO4J_URI, NEO4J_USERNAME, and "
                "NEO4J_PASSWORD in .env."
            )
        _driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        )
    return _driver


def close_driver():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def ensure_constraints():
    driver = get_driver()
    with driver.session() as session:
        for statement in STALE_CONSTRAINTS:
            session.run(statement)
        for statement in CONSTRAINTS:
            session.run(statement)
    logger.info("[NEO4J] Constraints ensured.")


# ensure_bootstrap_tenant() is gone. It created a fixed Pharmacy and a
# passwordless "owner" User from DEFAULT_PHARMACY_ID/DEFAULT_USER_ID, which
# was the stand-in for authentication before there was any. Now that
# registration provisions a workspace per account, a shared default tenant is
# not a fallback - it is a pile every new account would land in, which is the
# opposite of a clean slate.


def init_graph_db():
    """Best-effort startup hook: never crashes the app if Neo4j is unreachable."""
    try:
        ensure_constraints()
        # Imported here rather than at module scope: product_repository imports
        # get_driver from this module, so a top-level import would be circular.
        from db.product_repository import migrate_legacy_products, repair_provenance

        migrate_legacy_products()
        # Self-heals records written before confirmed/suggested were enforced
        # as disjoint. A no-op once there is nothing left to repair.
        repair_provenance()
    except Exception as e:
        logger.warning(f"[NEO4J] Startup initialization skipped: {type(e).__name__}: {e}")
