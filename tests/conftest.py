"""Suite-wide guards.

Why the scan ledger is stubbed for every test
---------------------------------------------
`.env` points at the production Neo4j Aura instance — there is no local
database — so anything that opens a driver during a test writes to live data.
Most of the suite is safe because it works against fake transactions, but the
upload tests walk the real ingestion path, and ingestion records a ledger row
before it does anything else.

That leak is quiet and it corrupts a number people read: running the suite
added scans for `test.png` and `blank.png` to the pharmacy's lifetime count.
Patching the individual tests would fix today's leak and not tomorrow's, since
the next upload test added would have to remember. Stubbing it here means a
test has to opt IN to touching the ledger.
"""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _never_write_to_the_scan_ledger():
    """Blocks ledger writes for every test. Reads are untouched — they are
    served from fakes anyway, and blocking them would hide real breakage."""
    with patch("db.repositories.scan_repository.record_scan", return_value=None), \
         patch("db.repositories.scan_repository.link_invoice"), \
         patch("db.repositories.scan_repository.mark_failed"), \
         patch("services.invoices.ingestion.scan_repository.record_scan", return_value=None), \
         patch("services.invoices.ingestion.scan_repository.link_invoice"), \
         patch("services.invoices.ingestion.scan_repository.mark_failed"):
        yield
