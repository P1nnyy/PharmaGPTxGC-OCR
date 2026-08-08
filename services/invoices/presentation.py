"""Turning stored invoices into what the API returns.

Only concern here is response shaping — presigning image URLs. Kept out of the
routers so both the invoice routes and the upload routes hand back an
identically-shaped invoice.
"""

from typing import Optional

from core.logger import logger
from services import image_storage


def presign_or_none(object_key: Optional[str]) -> Optional[str]:
    """Presigns one object key, returning None rather than raising.

    A presign failure must not take down a whole invoice listing: the invoice
    data is still useful without its image, so the failure is logged and the
    URL comes back empty.
    """
    if not object_key:
        return None
    try:
        return image_storage.get_presigned_url(object_key)
    except Exception as e:
        logger.warning(f"Failed to presign image URL for {object_key}: {e}")
        return None


def attach_image_urls(invoice: dict) -> dict:
    """Adds presigned URLs for every page of the invoice.

    `image_url` stays as page 1 so existing callers keep working; `image_urls`
    carries all pages in order. Invoices saved before multi-page support have no
    `source_image_refs`, so fall back to the single ref.
    """
    if invoice is None:
        return invoice

    refs = invoice.get("source_image_refs") or []
    if not refs and invoice.get("source_image_ref"):
        refs = [invoice["source_image_ref"]]

    urls = [u for u in (presign_or_none(ref) for ref in refs) if u]
    invoice["image_urls"] = urls
    invoice["image_url"] = urls[0] if urls else None
    invoice["page_count"] = invoice.get("page_count") or len(urls)
    return invoice
