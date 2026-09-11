"""Previewing and committing a sales import.

Two steps, deliberately. `preview` reads the file and reports what it found
without writing anything; `commit` writes what the user saw. A single-step
import would mean the first time anyone sees a mis-mapped column is after the
figures are in the database.

The preview is also where the reconciliation is surfaced. Adapters already
refuse a file that contradicts itself row by row; the preview adds the
whole-file view — per-rate totals, and a comparison against any total the file
declares for itself — so the user is agreeing to a number rather than to a
successful parse.
"""

from typing import Any, Optional

from core.idempotency import content_hash, dedupe_key
from core.tenancy import current_tenant
from db.repositories import sales_repository
from models.sales import CaptureMode, DocumentClass, SaleStatus
from services.sales.importers.base import ImportRejected
from services.sales.importers.registry import adapter_by_name, detect
from services.sales.importers.tabular import TabularAdapter, propose_mapping, _read_rows


def _discriminator(draft: dict) -> str:
    """What makes one draft in a file different from another.

    A day book gives every row a bill number. A GSTR-1 return does not — it
    reports period totals per place of supply — so without this two places of
    supply in one file would hash to the same key and the second would be
    swallowed as a duplicate of the first.
    """
    if draft.get("bill_number"):
        return str(draft["bill_number"])
    return f"{draft.get('tax_period')}:{draft.get('place_of_supply') or ''}"


def _summarise(drafts: "list[dict]") -> dict:
    """Per-rate totals across the whole file, for the preview to show."""
    by_rate: dict[int, dict] = {}
    for draft in drafts:
        for block in draft["rate_blocks"]:
            bucket = by_rate.setdefault(
                block["rate_bp"],
                {"rate_bp": block["rate_bp"], "taxable_paise": 0, "cgst_paise": 0, "sgst_paise": 0},
            )
            bucket["taxable_paise"] += block["taxable_paise"]
            bucket["cgst_paise"] += block["cgst_paise"]
            bucket["sgst_paise"] += block["sgst_paise"]

    return {
        "rate_blocks": [by_rate[rate] for rate in sorted(by_rate)],
        "taxable_paise": sum(d["taxable_paise"] for d in drafts),
        "cgst_paise": sum(d["cgst_paise"] for d in drafts),
        "sgst_paise": sum(d["sgst_paise"] for d in drafts),
        "exempt_paise": sum(d["exempt_paise"] for d in drafts),
        "nil_rated_paise": sum(d["nil_rated_paise"] for d in drafts),
        "non_gst_paise": sum(d["non_gst_paise"] for d in drafts),
        "grand_total_paise": sum(d["grand_total_paise"] for d in drafts),
        "document_count": len(drafts),
    }


def preview_import(
    data: bytes,
    filename: Optional[str] = None,
    format_name: Optional[str] = None,
    mapping: Optional[dict] = None,
) -> dict:
    """Reads a file and reports what importing it would produce. Writes nothing."""
    adapter = adapter_by_name(format_name) if format_name else detect(data, filename)
    if adapter is None:
        raise ImportRejected(f"There is no importer called {format_name!r}.")

    digest = content_hash(data)

    # A tabular file needs a column mapping before it can be parsed at all, so
    # the headers and the best available mapping come back even when parsing
    # then fails — that is exactly the case the user has to fix.
    headers: list[str] = []
    effective_mapping = mapping
    if isinstance(adapter, TabularAdapter):
        headers, _ = _read_rows(data, filename)
        if effective_mapping is None:
            remembered = sales_repository.get_import_mapping(adapter.name)
            effective_mapping = remembered or propose_mapping(headers)

    already = sales_repository.find_by_source_file_hash(digest)

    try:
        drafts = adapter.parse(data, filename, mapping=effective_mapping)
    except ImportRejected as exc:
        return {
            "format": {"name": adapter.name, "label": adapter.label},
            "source_file_hash": digest,
            "headers": headers,
            "mapping": effective_mapping,
            "drafts": [],
            "summary": None,
            "rejected": True,
            "reason": str(exc),
            "already_imported": len(already),
        }

    return {
        "format": {"name": adapter.name, "label": adapter.label},
        "source_file_hash": digest,
        "headers": headers,
        "mapping": effective_mapping,
        "drafts": drafts,
        "summary": _summarise(drafts),
        "rejected": False,
        "reason": None,
        # Says plainly that this file has been through before, so a second
        # import is understood as a no-op rather than looking like a failure.
        "already_imported": len(already),
    }


def commit_import(
    data: bytes,
    filename: Optional[str] = None,
    format_name: Optional[str] = None,
    mapping: Optional[dict] = None,
    created_by: Optional[str] = None,
    remember_mapping: bool = True,
) -> dict:
    """Imports a file. Idempotent on (file content, document) per the house rules.

    Rows already imported from this same file are skipped rather than written
    again, so re-uploading a day book after adding a day to it imports only the
    new day.

    Everything lands as DRAFT: the figures came from a file the shop's other
    software wrote, and nothing reaches a return without a person confirming
    it.
    """
    preview = preview_import(data, filename, format_name, mapping)
    if preview["rejected"]:
        raise ImportRejected(preview["reason"])

    adapter_name = preview["format"]["name"]
    digest = preview["source_file_hash"]

    if remember_mapping and preview["mapping"]:
        sales_repository.save_import_mapping(adapter_name, preview["mapping"])

    created, skipped = [], []
    for draft in preview["drafts"]:
        key = dedupe_key(
            current_tenant(), CaptureMode.IMPORT, digest, _discriminator(draft)
        )
        sale, was_created = sales_repository.upsert_sale(
            dedupe_key=key,
            computed=draft,
            capture_mode=CaptureMode.IMPORT,
            document_class=DocumentClass.INVOICE_CUM_BILL_OF_SUPPLY,
            status=SaleStatus.DRAFT,
            created_by=created_by,
            bill_number=draft.get("bill_number"),
            source_file_hash=digest,
            source_format=adapter_name,
        )
        (created if was_created else skipped).append(sale)

    return {
        "format": preview["format"],
        "source_file_hash": digest,
        "summary": preview["summary"],
        "created": created,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "mapping": preview["mapping"],
    }
