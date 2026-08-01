import os
import datetime
import json
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

from core.logger import logger
from extraction.base import DocumentExtractionEngine
from extraction.normalizers.canonical_invoice import CanonicalInvoice
from extraction.normalizers.azure_invoice_normalizer import normalize_azure_invoice
from services import cache_service

class AzureDocumentIntelligenceEngine(DocumentExtractionEngine):
    """
    Document extraction engine powered by Azure Document Intelligence.
    Reads credentials from the environment, sends local invoice images to
    the Azure endpoint, logs raw responses, and parses/normalizes results.
    """
    
    def __init__(self):
        # Automatically load environment variables from local .env file
        load_dotenv(".env")
        
        # 1. Read Azure configuration settings from the environment.
        # DOCUMENTINTELLIGENCE_* is the primary name; AZURE_DOCUMENT_* (used by
        # core/config.py Settings) is accepted as a fallback for consistency.
        self.endpoint = os.environ.get("DOCUMENTINTELLIGENCE_ENDPOINT") or os.environ.get("AZURE_DOCUMENT_ENDPOINT")
        self.api_key = os.environ.get("DOCUMENTINTELLIGENCE_API_KEY") or os.environ.get("AZURE_DOCUMENT_KEY")
        self.model_id = os.environ.get("AZURE_DI_MODEL_ID", "prebuilt-invoice")
        
        # 2. Determine whether raw response JSON caching is requested
        save_raw_str = os.environ.get("AZURE_DI_SAVE_RAW", "false").lower().strip()
        self.save_raw = save_raw_str in ("true", "1", "yes")

    def extract(self, document_path: str, bypass_cache: bool = False, **kwargs) -> CanonicalInvoice:
        """
        Submits the target document to Azure Document Intelligence and normalizes the response.

        The raw Azure response is cached by content hash, so re-analyzing the
        same bytes is free. Normalization always re-runs against that raw
        response rather than being cached itself - normalizer fixes then apply
        to already-scanned documents without paying Azure again.

        Args:
            document_path: Path to the target invoice image file.
            bypass_cache: Force a live Azure call, overwriting any cached response.
            **kwargs: Extra parameters (not utilized currently).

        Returns:
            A normalized CanonicalInvoice representation of the extracted document.
        """
        # Validate endpoint configuration
        if not self.endpoint:
            raise ValueError(
                "DOCUMENTINTELLIGENCE_ENDPOINT is not configured. "
                "Ensure it is set in your .env or environment variables."
            )
            
        # Validate API Key configuration
        if not self.api_key:
            raise ValueError(
                "DOCUMENTINTELLIGENCE_API_KEY is not configured. "
                "Ensure it is set in your .env or environment variables."
            )
            
        # Validate target file existence
        doc_path = Path(document_path)
        if not doc_path.exists():
            raise FileNotFoundError(f"Document file not found at: '{document_path}'")
            
        # 3. Read the document once, so the same bytes are used both for the
        # cache key and for the request body.
        with open(doc_path, "rb") as f:
            document_bytes = f.read()

        # 4. Try the raw-response cache before spending an API call. Any
        # failure to derive a key (unreadable/oddly-typed bytes) just disables
        # caching for this call - the cache is an optimization and must never
        # be able to block an extraction.
        cache_key = None
        try:
            cache_key = cache_service.azure_cache_key(document_bytes, self.model_id)
        except Exception as e:
            logger.warning(f"[AZURE CACHE] key derivation skipped: {type(e).__name__}: {e}")

        if cache_key and not bypass_cache:
            cached = cache_service.get_cached_azure_response(cache_key)
            if cached is not None:
                # Normalization intentionally re-runs on the cached response.
                return normalize_azure_invoice(cached)

        # 5. Cache miss (or forced bypass): instantiate the client and make the
        # billable call.
        client = DocumentIntelligenceClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.api_key)
        )

        logger.info(f"[AZURE CACHE] calling Azure Document Intelligence (model={self.model_id})")
        poller = client.begin_analyze_document(
            model_id=self.model_id,
            body=document_bytes
        )
        result = poller.result()

        # 6. Convert response objects into a plain python dictionary
        result_dict = result.as_dict()

        if cache_key:
            cache_service.save_azure_response(cache_key, result_dict)

        # 7. Save raw JSON data locally if requested (debug aid, separate from
        # the response cache above)
        if self.save_raw:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = Path("local_runs/azure_engine")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{timestamp}_azure_raw.json"
            
            try:
                with open(output_path, "w", encoding="utf-8") as out_f:
                    json.dump(result_dict, out_f, indent=2, default=str)
            except Exception as e:
                # Silently catch disk write/permission warnings to prevent pipeline disruption
                pass
                
        # 8. Normalize raw response payload to the CanonicalInvoice schema
        canonical_invoice = normalize_azure_invoice(result_dict)
        return canonical_invoice

