from typing import Optional

import boto3
from botocore.client import Config as BotoConfig

from core.config import settings
from core.logger import logger

_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.R2_ACCOUNT_ID or not settings.R2_ACCESS_KEY_ID or not settings.R2_SECRET_ACCESS_KEY:
            raise ValueError(
                "Cloudflare R2 is not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY, and R2_BUCKET_NAME in .env."
            )
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=BotoConfig(signature_version="s3v4"),
            region_name="auto",
        )
    return _client


def upload_invoice_image(
    pharmacy_id: str,
    invoice_id: str,
    file_bytes: bytes,
    content_type: str = "image/jpeg",
    extension: str = "jpg",
) -> str:
    """Uploads invoice image bytes to R2 and returns the object key (not a URL)."""
    client = _get_client()
    object_key = f"{pharmacy_id}/{invoice_id}.{extension.lstrip('.')}"
    client.put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=object_key,
        Body=file_bytes,
        ContentType=content_type,
    )
    logger.info(f"[R2] Uploaded invoice image to {object_key}")
    return object_key


def get_presigned_url(object_key: str, expires_in: int = 900) -> str:
    """Generates a short-lived signed GET URL for a private R2 object."""
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.R2_BUCKET_NAME, "Key": object_key},
        ExpiresIn=expires_in,
    )


def delete_invoice_image(object_key: str) -> None:
    client = _get_client()
    client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=object_key)
