"""Purchase reporting.

Layering, outermost first:

    api/routers/reports.py   HTTP shape, period parsing, error mapping
    services/reports/*       report composition and all business rules
    db/repositories/         Cypher aggregation

`calculations` holds the pure maths and depends on nothing; every other module
here composes it with repository rows. Nothing in this package touches FastAPI
or Neo4j directly, which is what keeps the rules testable without either.

A rule that holds throughout: a figure that cannot be computed is reported as
missing, never as zero. Reports drive purchasing decisions, and an invented
number is worse than an absent one.
"""

from services.reports import calculations, expiry, gst, overview, periods, procurement, quality

__all__ = [
    "calculations",
    "expiry",
    "gst",
    "overview",
    "periods",
    "procurement",
    "quality",
]
