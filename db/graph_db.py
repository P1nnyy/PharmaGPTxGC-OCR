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


def ensure_bootstrap_tenant():
    """Creates the default Pharmacy/User used until real multi-tenant auth exists."""
    driver = get_driver()
    with driver.session() as session:
        session.run(
            """
            MERGE (ph:Pharmacy {id: $pharmacy_id})
            ON CREATE SET ph.name = $pharmacy_name, ph.created_at = datetime()
            MERGE (u:User {id: $user_id})
            ON CREATE SET u.email = $user_email, u.name = $pharmacy_name,
                          u.role = 'owner', u.created_at = datetime()
            MERGE (u)-[:MEMBER_OF {role: 'owner'}]->(ph)
            """,
            pharmacy_id=settings.DEFAULT_PHARMACY_ID,
            pharmacy_name=settings.DEFAULT_PHARMACY_NAME,
            user_id=settings.DEFAULT_USER_ID,
            user_email=settings.DEFAULT_USER_EMAIL,
        )
    logger.info("[NEO4J] Bootstrap tenant ensured.")


def init_graph_db():
    """Best-effort startup hook: never crashes the app if Neo4j is unreachable."""
    try:
        ensure_constraints()
        ensure_bootstrap_tenant()
        # Imported here rather than at module scope: product_repository imports
        # get_driver from this module, so a top-level import would be circular.
        from db.product_repository import migrate_legacy_products

        migrate_legacy_products()
    except Exception as e:
        logger.warning(f"[NEO4J] Startup initialization skipped: {type(e).__name__}: {e}")
