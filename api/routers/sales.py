"""Sales: the outward-supply side of the return.

Three ways in, and they exist because a pharmacy will not change its counter
workflow to adopt us:

  POST /sales/day-total   - declare a day's totals per GST slab
  POST /sales/from-image  - photograph the shop's own counter bill
  POST /sales/import      - upload a day book or sales register export

All three set `capture_mode`, and reporting reads it to decide what it may
claim. Routes stay thin: the arithmetic is in `services/sales/`, the Cypher in
`db/repositories/sales_repository.py`.

Route order is load-bearing. `/sales/day-total` and `/sales/periods/...` are
declared before `/sales/{sale_id}`, because FastAPI matches in declaration
order and would otherwise read "day-total" as a sale id.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from api.deps import current_user
from core.idempotency import content_hash, dedupe_key
from core.logger import logger
from core.serials import SerialError, financial_year_of, is_valid_serial, parse_serial
from core.tax_periods import PeriodError, is_valid_period, period_bounds, period_label, period_of
from core.tenancy import current_tenant
from db.repositories import audit_repository, pharmacy_repository, sales_repository, serial_repository
from db.repositories.sales_repository import PeriodFiledError
from extraction.normalizers.canonical_invoice import DocumentRole
from extraction.router import get_extraction_engine
from models.sales import CaptureMode, CAPTURE_MODES_WITH_LINES, CAPTURE_MODES_WITH_STOCK, DayTotalRequest, PaymentInput
from services import image_storage
from services.invoices.ingestion import extract_from_bytes, read_and_gate
from services.sales.day_total import DayTotalError, record_day_total, recompute_day_total
from services.sales.importers.base import ImportRejected
from services.sales.importers.registry import describe as describe_importers
from services.sales.importing import commit_import, preview_import
from services.sales.from_image import (
    SaleMappingError,
    find_existing_by_image,
    record_sale_from_image,
)

router = APIRouter(prefix="/sales", tags=["sales"])


class FilePeriodRequest(BaseModel):
    period: str


class SerialBlockRequest(BaseModel):
    """Asked for when a counter opens, never during a sale."""

    device_id: str
    prefix: str
    size: int = serial_repository.DEFAULT_BLOCK_SIZE
    pad_to: int = 6
    financial_year: Optional[int] = None


class SaleLineIn(BaseModel):
    line_id: str
    product_id: Optional[str] = None
    product_name: str
    hsn: Optional[str] = None
    batch_number: Optional[str] = None
    expiry: Optional[str] = None
    quantity: float
    unit_price_paise: Optional[int] = None
    taxable_paise: Optional[int] = None
    cgst_paise: Optional[int] = None
    sgst_paise: Optional[int] = None
    rate_bp: Optional[int] = None
    line_total_paise: Optional[int] = None
    # Whatever the scanner read, kept whether or not it parsed.
    scanned_code_raw: Optional[str] = None


class CounterSaleRequest(BaseModel):
    """A bill issued on a device, arriving whenever the network came back.

    Every figure is integer paise and was computed on the device at issue time.
    The server does not recompute them: the bill in the customer's hand says
    what it says, and a server that disagreed would be describing a different
    document.
    """

    serial: str
    sale_date: str
    issued_at: str
    device_id: str
    lines: list[SaleLineIn] = []
    totals: dict = {}
    payments: list[PaymentInput] = []
    prescription_image_ref: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None


_AGGREGATE_NOTE = {
    CaptureMode.DAY_TOTAL: (
        "Declared daily totals. No line items, batches, stock movements or "
        "margin data sit behind this record — it is sufficient for B2CS in "
        "GSTR-1 and for nothing that implies item-level detail."
    ),
    CaptureMode.IMPORT: (
        "Imported as period-level totals rather than individual bills. No line "
        "items or stock movements sit behind this record."
    ),
}


def _reporting_caveat(sale: dict) -> dict:
    """What this record can and cannot be used to claim.

    Travels with every sale rather than being left for each report to work
    out. A downstream consumer that does not know a figure is an aggregate
    will happily compute a margin from it and present the result as precise.

    Read from the record, not inferred from its capture mode alone: a day book
    imported row by row carries lines, and a GSTR-1 summary imported through
    the same endpoint does not. The mode says where it came from; only the
    record knows what is actually in it.
    """
    capture_mode = sale.get("capture_mode", "")
    is_aggregate = bool(sale.get("is_aggregate"))
    has_lines = (capture_mode in CAPTURE_MODES_WITH_LINES) and not is_aggregate
    return {
        "has_line_items": has_lines,
        "moves_stock": capture_mode in CAPTURE_MODES_WITH_STOCK,
        "is_aggregate": is_aggregate,
        "capture_mode": capture_mode,
        "note": _AGGREGATE_NOTE.get(capture_mode) if is_aggregate else None,
    }


def _present(sale: dict) -> dict:
    return {**sale, "reporting": _reporting_caveat(sale)}


@router.post("")
async def record_counter_sale(
    payload: CounterSaleRequest, response: Response, user: dict = Depends(current_user)
):
    """Records a bill issued at the counter, usually offline and synced later.

    **Idempotent on (series, number, financial year)**, and the key is computed
    here from the serial rather than accepted from the client. That is the
    whole reason sync needs no ordering and no conflict resolver: serial blocks
    are disjoint per device, so two bills can never claim one number, and a
    replayed POST lands on the record that already exists.

    A bill that fails a check is still stored. It was printed and handed over
    before this request was made, so "reject" is not an outcome the world
    supports — shortfalls come back as `issues` to reconcile.
    """
    if not is_valid_serial(payload.serial):
        raise HTTPException(
            status_code=400,
            detail=f"{payload.serial!r} is not a Rule 46(b) serial.",
        )
    try:
        prefix, sequence = parse_serial(payload.serial)
        financial_year = financial_year_of(payload.sale_date)
        tax_period = period_of(payload.sale_date)
    except (SerialError, PeriodError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # (series, number, FY) within a workspace — exactly the invariant the
    # offline design rests on, enforced where it cannot be bypassed.
    key = dedupe_key(current_tenant(), "SALE_SERIAL", prefix, str(financial_year), str(sequence))

    sale, created, issues = await run_in_threadpool(
        sales_repository.save_counter_sale,
        payload.serial,
        key,
        payload.sale_date,
        tax_period,
        financial_year,
        [line.model_dump() for line in payload.lines],
        payload.totals,
        [p.model_dump() for p in payload.payments],
        payload.device_id,
        payload.issued_at,
        payload.prescription_image_ref,
        payload.customer_name,
        payload.customer_phone,
        user.get("id"),
    )

    if created:
        audit_repository.record(
            action="sale.counter.recorded",
            actor=user,
            target_type="Sale",
            target_id=sale.get("id"),
            summary=f"Recorded counter bill {payload.serial}",
        )

    response.status_code = 201 if created else 200
    return {
        **_present(sale),
        "created": created,
        # Never an error status: the bill exists whatever these say.
        "issues": issues,
        "needs_reconciliation": bool(issues),
    }


@router.post("/serial-blocks", status_code=201)
async def allocate_serial_block(payload: SerialBlockRequest, user: dict = Depends(current_user)):
    """Hands this device a range of invoice serials it alone owns.

    Called when a counter opens and whenever a block runs low — never during a
    sale, because a sale may have no network at all.
    """
    financial_year = payload.financial_year
    if financial_year is None:
        from datetime import date

        financial_year = financial_year_of(date.today().isoformat())
    try:
        block = await run_in_threadpool(
            serial_repository.allocate_block,
            payload.prefix,
            financial_year,
            payload.device_id,
            payload.size,
            payload.pad_to,
        )
    except SerialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_repository.record(
        action="sale.serial_block.allocated",
        actor=user,
        target_type="SerialBlock",
        target_id=block["id"],
        summary=f"Allocated {payload.prefix}{block['from_sequence']}-{block['to_sequence']} to {payload.device_id}",
    )
    return block


@router.get("/serial-blocks")
async def list_serial_blocks(device_id: str = Query(...), user: dict = Depends(current_user)):
    """What this device already owns — so a wiped device recovers its range
    instead of being handed a new one and leaving a hole in the series."""
    return {"blocks": await run_in_threadpool(serial_repository.blocks_for_device, device_id)}


@router.post("/day-total")
async def create_day_total(
    payload: DayTotalRequest, response: Response, user: dict = Depends(current_user)
):
    """Declares one day's sales as per-slab totals.

    Idempotent on the date: posting the same day twice returns the record
    already stored with `created: false` and a 200 rather than a 201, instead
    of declaring the same output tax again. Correcting a day that is already
    entered is a PATCH — a deliberate act rather than a retry.
    """
    try:
        sale, created = await run_in_threadpool(
            record_day_total, payload.model_dump(), user.get("id")
        )
    except DayTotalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PeriodFiledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if created:
        audit_repository.record(
            action="sale.day_total.created",
            actor=user,
            target_type="Sale",
            target_id=sale.get("id"),
            summary=f"Declared day total for {sale.get('sale_date')}",
        )

    body = {**_present(sale), "created": created}
    if created:
        response.status_code = 201
    else:
        # Not an error: a client retrying after a timeout has done nothing
        # wrong, and the right answer is the record that already exists.
        response.status_code = 200
        body["message"] = (
            f"A day total for {sale.get('sale_date')} was already recorded. "
            "Nothing was changed — edit it if the figures need correcting."
        )
    return body


@router.post("/from-image")
async def create_sale_from_image(
    response: Response,
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
):
    """Reads a bill the shop printed itself and lands it as a draft.

    Routed through the same extraction stack as a purchase invoice, with the
    document role set to SALE — the parsing is identical, and only who "we" are
    on the page and where the result is mapped differ.

    Idempotent on the image's content hash together with the bill number found
    on it. The hash is checked before anything is extracted, because extraction
    is billable and re-uploading a photograph we already hold should cost
    nothing.

    Always lands as DRAFT. A machine read these figures off a photograph and
    nothing reaches a return without a person confirming it.
    """
    file_bytes = await read_and_gate(file, "Bill")
    digest = content_hash(file_bytes)

    already = await run_in_threadpool(find_existing_by_image, digest)
    if already is not None:
        response.status_code = 200
        return {
            **_present(already),
            "created": False,
            "message": (
                "This exact image has already been read — nothing was extracted "
                "again. Open the draft to review it."
            ),
        }

    # The shop's own registration is what turns the seller/buyer decision from
    # a layout heuristic into a fact. Absent, the heuristic still applies.
    profile = await run_in_threadpool(pharmacy_repository.get_profile, current_tenant())
    own_gstin = (profile or {}).get("gstin")

    engine = get_extraction_engine()
    try:
        canonical = await extract_from_bytes(
            engine,
            file_bytes,
            file.filename,
            bypass_cache=False,
            document_role=DocumentRole.SALE,
            own_gstin=own_gstin,
        )
    except Exception as exc:
        logger.error(f"Sale extraction failed: {exc}")
        raise HTTPException(status_code=502, detail="Could not read that bill. Try a clearer photo.") from exc

    object_key = None
    try:
        extension = (Path(file.filename or "bill.jpg").suffix or ".jpg").lstrip(".") or "jpg"
        object_key = await run_in_threadpool(
            image_storage.upload_invoice_image,
            current_tenant(),
            f"sale_{digest[:16]}",
            file_bytes,
            file.content_type or "image/jpeg",
            extension,
        )
    except Exception as exc:
        # The extraction already succeeded and was paid for; losing it because
        # object storage hiccuped would mean paying for it twice. The draft is
        # saved without the image and says so.
        logger.error(f"Could not store the bill image: {exc}")

    try:
        sale, created, mapping = await run_in_threadpool(
            record_sale_from_image, canonical, digest, object_key, user.get("id")
        )
    except SaleMappingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PeriodFiledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if created:
        audit_repository.record(
            action="sale.from_image.created",
            actor=user,
            target_type="Sale",
            target_id=sale.get("id"),
            summary=f"Read a counter bill dated {sale.get('sale_date')}",
        )

    response.status_code = 201 if created else 200
    return {
        **_present(sale),
        "created": created,
        "image_stored": object_key is not None,
        # Everything the reviewer has to settle before this can be confirmed.
        "pricing_basis": mapping["pricing_basis"],
        "reconciliation": mapping["reconciliation"],
        "review_notes": mapping["review_notes"],
        "printed_totals": mapping["printed_totals"],
    }


@router.get("/import/formats")
async def import_formats(user: dict = Depends(current_user)):
    """The file formats the importer recognises."""
    return {"formats": describe_importers()}


@router.post("/import/preview")
async def preview_sales_import(
    file: UploadFile = File(...),
    format_name: Optional[str] = Query(None, description="Force an importer instead of sniffing."),
    mapping_json: Optional[str] = Query(None, description="Column mapping as JSON."),
    user: dict = Depends(current_user),
):
    """Reads a file and reports what importing it would produce. Writes nothing.

    This is where a mis-mapped column is meant to be caught: the response
    carries the per-rate totals the file would produce, so the user agrees to a
    number rather than to a successful parse.
    """
    data = await file.read()
    mapping = _parse_mapping(mapping_json)
    try:
        return await run_in_threadpool(
            preview_import, data, file.filename, format_name, mapping
        )
    except ImportRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/import")
async def import_sales(
    file: UploadFile = File(...),
    format_name: Optional[str] = Query(None, description="Force an importer instead of sniffing."),
    mapping_json: Optional[str] = Query(None, description="Column mapping as JSON."),
    remember_mapping: bool = Query(True, description="Reuse this mapping for the next file of this format."),
    user: dict = Depends(current_user),
):
    """Imports a day book, sales register or GSTR-1 JSON.

    Idempotent on the file's content together with each document in it, so
    re-uploading a day book after another day was added to it imports only the
    new day. Everything lands as DRAFT.
    """
    data = await file.read()
    mapping = _parse_mapping(mapping_json)
    try:
        result = await run_in_threadpool(
            commit_import, data, file.filename, format_name, mapping, user.get("id"), remember_mapping
        )
    except ImportRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PeriodFiledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    audit_repository.record(
        action="sale.import.committed",
        actor=user,
        target_type="Sale",
        target_id=result["source_file_hash"][:16],
        summary=(
            f"Imported {result['created_count']} document(s) from "
            f"{file.filename} ({result['format']['label']})"
        ),
    )
    return {
        **result,
        "created": [_present(sale) for sale in result["created"]],
    }


def _parse_mapping(mapping_json: Optional[str]) -> Optional[dict]:
    """Reads the column mapping off the query string, or refuses it clearly."""
    if not mapping_json:
        return None
    import json

    try:
        mapping = json.loads(mapping_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="The column mapping is not valid JSON.") from exc
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=400, detail="The column mapping must be an object.")
    return mapping


@router.post("/periods/file")
async def file_period(payload: FilePeriodRequest, user: dict = Depends(current_user)):
    """Closes a period. Everything in it becomes immutable from this point.

    Filing is what turns "records we are still working on" into "records behind
    a filed return", and the house rules make the second kind immutable —
    corrections after this are new documents, not edits.
    """
    if not is_valid_period(payload.period):
        raise HTTPException(status_code=400, detail=f"{payload.period!r} is not a tax period. Use MMYYYY.")

    result = await run_in_threadpool(sales_repository.mark_period_filed, payload.period, user.get("id"))
    audit_repository.record(
        action="tax_period.filed",
        actor=user,
        target_type="TaxPeriod",
        target_id=payload.period,
        summary=f"Filed {period_label(payload.period)}",
    )
    return {"period": payload.period, "label": period_label(payload.period), **result}


@router.get("/periods/{period}")
async def period_status(period: str, user: dict = Depends(current_user)):
    """Whether a period is still open for editing."""
    if not is_valid_period(period):
        raise HTTPException(status_code=400, detail=f"{period!r} is not a tax period. Use MMYYYY.")
    filed = await run_in_threadpool(sales_repository.is_period_filed, period)
    return {"period": period, "label": period_label(period), "filed": filed}


@router.get("")
async def list_sales(
    start: Optional[str] = Query(None, description="ISO date, inclusive."),
    end: Optional[str] = Query(None, description="ISO date, inclusive."),
    period: Optional[str] = Query(None, description="MMYYYY. Overrides start/end."),
    capture_mode: Optional[str] = Query(None, description="Comma-separated capture modes."),
    status: Optional[str] = Query(None, description="Comma-separated statuses."),
    user: dict = Depends(current_user),
):
    """Sales in a window, newest first."""
    if period:
        try:
            start, end = period_bounds(period)
        except PeriodError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not start or not end:
        raise HTTPException(status_code=400, detail="Give either a period, or a start and end date.")

    modes = [m.strip().upper() for m in capture_mode.split(",")] if capture_mode else None
    statuses = [s.strip().upper() for s in status.split(",")] if status else None

    rows = await run_in_threadpool(sales_repository.list_sales, start, end, modes, statuses)
    return {
        "sales": [_present(sale) for sale in rows],
        "count": len(rows),
        "start": start,
        "end": end,
    }


@router.get("/{sale_id}")
async def get_sale(sale_id: str, user: dict = Depends(current_user)):
    sale = await run_in_threadpool(sales_repository.get_sale, sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="No such sale in this workspace.")
    return _present(sale)


@router.patch("/{sale_id}/day-total")
async def edit_day_total(sale_id: str, payload: DayTotalRequest, user: dict = Depends(current_user)):
    """Corrects a day total. Refused once its period is filed."""
    try:
        sale = await run_in_threadpool(
            recompute_day_total, sale_id, payload.model_dump(), user.get("id")
        )
    except DayTotalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PeriodFiledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    audit_repository.record(
        action="sale.day_total.updated",
        actor=user,
        target_type="Sale",
        target_id=sale_id,
        summary=f"Corrected day total for {sale.get('sale_date')}",
    )
    return _present(sale)
