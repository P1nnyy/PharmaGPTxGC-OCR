"""Deterministic dedupe keys for every write path that ingests a document.

The house rule: a write path that takes in an external document must be
idempotent on a deterministic key. The reason it is ranked highest-severity is
that the failure is silent — a purchase invoice ingested twice double-claims
input tax credit, and a sale ingested twice double-declares output tax. Neither
throws; both just make the return wrong.

"Deterministic" is doing real work in that sentence. The key must be computable
from the document alone, identically, on every attempt — so a retry after a
timeout, a re-uploaded file, or a user pressing the button twice all land on the
same key and the second write becomes a no-op rather than a second document.

The keys in use:

  * day total   - (pharmacy, DAY_TOTAL, sale date)
  * bill photo  - (pharmacy, BILL_PHOTO, image content hash, bill number)
  * import row  - (pharmacy, IMPORT, source file hash, bill number)
"""

import hashlib
from typing import Optional

# A separator that cannot occur inside any part, so parts cannot be shifted
# across the boundary between them. Without this, ("a", "bc") and ("ab", "c")
# hash identically and two unrelated documents silently become one.
_SEPARATOR = "\x1f"

# Distinct from an empty string, so "this field was absent" and "this field was
# blank" are different documents rather than the same one.
_ABSENT = "\x00<absent>"


def content_hash(data: bytes) -> str:
    """SHA-256 of a file's bytes, hex encoded.

    Bytes rather than a filename or a size: two photographs of the same bill
    are different documents, and the same file uploaded twice is not. Only the
    content can tell those apart.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("content_hash expects bytes")
    return hashlib.sha256(bytes(data)).hexdigest()


def _normalise(part: Optional[str]) -> str:
    """Folds away differences that do not make a document different.

    A bill number retyped as ` inv-001 ` is the same bill as `INV-001`, and
    treating them as distinct would let one bill be filed twice. Anything more
    aggressive than case and outer whitespace is deliberately not folded —
    `INV-1` and `INV-01` are different numbers and only the shop knows which.
    """
    if part is None:
        return _ABSENT
    return str(part).strip().casefold()


def dedupe_key(*parts: Optional[str]) -> str:
    """A stable key for the parts that identify one document.

    Returned as a hash rather than the joined parts so the key is a fixed
    length whatever goes into it, and so it can be an indexed property without
    a bill number's punctuation ending up in the index.
    """
    if not parts:
        raise ValueError("dedupe_key needs at least one part")
    joined = _SEPARATOR.join(_normalise(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
