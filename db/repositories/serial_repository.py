"""Allocating blocks of invoice serials to devices.

This is the load-bearing invariant of the whole offline design.

Bills are issued on a device with no network, so the serial cannot be asked for
at sale time — the device has to already hold a range it owns. Sync is then
free of ordering requirements and free of merge conflicts, but *only* because
no two devices can ever be handed the same number. There is no conflict
resolver downstream to catch it if that fails; there is nothing to catch it
with, because two bills with the same serial are indistinguishable in a return.

So the allocation is a single atomic statement. `MERGE` takes a write lock on
the counter node, the read and the increment happen inside one transaction, and
two devices asking at the same instant are serialised by the database rather
than by anything this code does. Reading the counter and writing it back in two
statements would look identical in a test and hand out overlapping blocks the
first time two counters opened together.

The counter is per workspace, series and financial year, because Rule 46(b)
makes serials unique within a year and the sequence restarts each April.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from core.serials import SerialError, format_serial, series_key
from core.tenancy import current_tenant
from db.graph_db import get_driver

# Big enough that a busy counter does not come back for another block mid-shift,
# small enough that a device lost with an unused block does not burn a large
# hole in the series. A gap is not fatal — Rule 46(b) wants consecutive
# numbering, and an unused allocated range is explainable — but it is untidy.
DEFAULT_BLOCK_SIZE = 200

# Guards a runaway caller from exhausting a year's series in one request.
MAX_BLOCK_SIZE = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_write(query: str, **params) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_write(lambda tx: [r.data() for r in tx.run(query, **params)])


def _run_read(query: str, **params) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        return session.execute_read(lambda tx: [r.data() for r in tx.run(query, **params)])


def allocate_block(
    prefix: str,
    financial_year: int,
    device_id: str,
    size: int = DEFAULT_BLOCK_SIZE,
    pad_to: int = 6,
    pharmacy_id: Optional[str] = None,
) -> dict:
    """Hands a device a contiguous range of serials it alone owns.

    Called when a counter opens, never during a sale.

    The length check happens here rather than at sale time: a device that has
    already issued bills cannot usefully be told its serial is too long, so the
    last serial in the block is formatted now and the whole allocation is
    refused if it will not fit inside Rule 46(b)'s sixteen characters.
    """
    if size < 1 or size > MAX_BLOCK_SIZE:
        raise SerialError(f"A block must be between 1 and {MAX_BLOCK_SIZE} serials.")
    pharmacy_id = pharmacy_id or current_tenant()

    rows = _run_write(
        """
        MERGE (s:SerialSeries {key: $key})
        ON CREATE SET s.pharmacy_id = $pharmacy_id, s.prefix = $prefix,
                      s.financial_year = $financial_year, s.next_sequence = 1,
                      s.created_at = $now
        // Read and increment inside one statement, under the write lock MERGE
        // already took. Splitting these is what hands two devices the same range.
        SET s.next_sequence = s.next_sequence + $size
        RETURN s.next_sequence - $size AS from_sequence,
               s.next_sequence - 1     AS to_sequence
        """,
        key=series_key(pharmacy_id, prefix, financial_year),
        pharmacy_id=pharmacy_id,
        prefix=prefix,
        financial_year=financial_year,
        size=size,
        now=_now(),
    )
    if not rows:
        raise SerialError("The serial counter could not be read.")

    from_sequence = int(rows[0]["from_sequence"])
    to_sequence = int(rows[0]["to_sequence"])

    # Raises if the last serial in the range would be too long. Deliberately
    # after the increment: the range is burned either way, and a series that
    # has outgrown its prefix must stop rather than silently wrap.
    format_serial(prefix, to_sequence, pad_to)

    block_id = str(uuid.uuid4())
    _run_write(
        """
        MATCH (s:SerialSeries {key: $key})
        CREATE (b:SerialBlock {
            id: $block_id, pharmacy_id: $pharmacy_id, device_id: $device_id,
            prefix: $prefix, financial_year: $financial_year,
            from_sequence: $from_sequence, to_sequence: $to_sequence,
            pad_to: $pad_to, allocated_at: $now
        })
        CREATE (b)-[:FROM_SERIES]->(s)
        """,
        key=series_key(pharmacy_id, prefix, financial_year),
        block_id=block_id,
        pharmacy_id=pharmacy_id,
        device_id=device_id,
        prefix=prefix,
        financial_year=financial_year,
        from_sequence=from_sequence,
        to_sequence=to_sequence,
        pad_to=pad_to,
        now=_now(),
    )

    return {
        "id": block_id,
        "prefix": prefix,
        "financial_year": financial_year,
        "from_sequence": from_sequence,
        "to_sequence": to_sequence,
        "next_sequence": from_sequence,
        "pad_to": pad_to,
        "device_id": device_id,
        "allocated_at": _now(),
    }


def blocks_for_device(device_id: str, pharmacy_id: Optional[str] = None) -> list[dict]:
    """Every block this device has been given, newest first.

    Lets a device that lost its local database recover what it owns instead of
    being handed a fresh block and leaving a hole in the series.
    """
    pharmacy_id = pharmacy_id or current_tenant()
    rows = _run_read(
        """
        MATCH (b:SerialBlock {device_id: $device_id, pharmacy_id: $pharmacy_id})
        RETURN b {.*} AS block
        ORDER BY block.allocated_at DESC
        """,
        device_id=device_id,
        pharmacy_id=pharmacy_id,
    )
    return [row["block"] for row in rows]
