import io
from pathlib import Path
from typing import Any, Dict
from PIL import Image
import torch

from core.config import settings
from core.logger import logger
from extraction.base import DocumentExtractionEngine
from services import cache_service, ocr_engine, spatial_reconstruction
from services.diagnostics_writer import (
    normalize_orientation_metadata,
    write_upload_diagnostics,
)
from services.llm_extractor import LLMExtractor
from services.validators.image_validator import ImageValidator

# Mark legacy modules: Add warning comments near entry points
# This module is part of the legacy extraction path.
# It should remain available as fallback during Azure Document Intelligence migration.
# Do not delete until Azure shadow comparison proves replacement quality.

def _is_no_valid_table_candidate(metadata: Dict[str, Any]) -> bool:
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    return (
        metadata.get("fast_fail_reason") == "no_valid_table_candidate"
        or metrics.get("no_valid_table_candidate") is True
        or metadata.get("selected_table_available") is False
        or metrics.get("selected_table_available") is False
    )


def _safe_tax_summary() -> Dict[str, float]:
    return {
        "taxable_value": 0.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "igst": 0.0,
        "total_gst": 0.0,
        "total_tax": 0.0,
    }


def _safe_llm_extraction_defaults() -> Dict[str, Any]:
    return {
        "metadata": {},
        "items": [],
        "scheme_items": [],
        "credit_notes": [],
        "subtotal": 0.0,
        "tax": _safe_tax_summary(),
        "grand_total": 0.0,
        "extra_data": {"fast_fail_reason": "no_valid_table_candidate"},
    }


def _apply_no_valid_table_response_defaults(
    metadata: Dict[str, Any],
    *,
    invoice_id: str,
    filename: str | None,
) -> Dict[str, Any]:
    if not _is_no_valid_table_candidate(metadata):
        return metadata

    metadata["invoice_id"] = metadata.get("invoice_id") or invoice_id
    metadata["filename"] = filename
    metadata["fast_fail"] = True
    metadata["fast_fail_reason"] = "no_valid_table_candidate"
    metadata["selected_table_available"] = False
    metadata["selected_table_id"] = None
    metadata["safe_for_erp"] = False
    metadata["status_effective"] = metadata.get("status_effective") or "failed"
    metadata.setdefault("item_rows_clean", [])
    metadata.setdefault("scheme_rows", [])
    metadata.setdefault("credit_note_rows", [])
    metadata.setdefault("invoice_totals", {})
    metadata["invoice_totals"].setdefault("subtotal", 0.0)
    metadata["invoice_totals"].setdefault("grand_total", 0.0)
    metadata["invoice_totals"].setdefault("tax", _safe_tax_summary())
    metadata.setdefault("llm_extraction", _safe_llm_extraction_defaults())

    quality_gate = metadata.get("quality_gate") if isinstance(metadata.get("quality_gate"), dict) else {}
    reasons = list(quality_gate.get("reasons") or [])
    if "no_valid_table_candidate" not in reasons:
        reasons.append("no_valid_table_candidate")
    quality_gate.update({
        "status": quality_gate.get("status") or metadata["status_effective"],
        "safe_for_erp": False,
        "reasons": reasons,
        "confidence": quality_gate.get("confidence", metadata.get("invoice_confidence", 0.0)),
    })
    metadata["quality_gate"] = quality_gate

    canonical = metadata.get("canonical_invoice") if isinstance(metadata.get("canonical_invoice"), dict) else {}
    canonical.setdefault("invoice_id", invoice_id)
    canonical.setdefault("item_rows", [])
    canonical.setdefault("footer_fields", {})
    canonical.setdefault("totals", {})
    canonical["totals"].setdefault("subtotal", 0.0)
    canonical["totals"].setdefault("grand_total", 0.0)
    canonical["totals"].setdefault("tax", _safe_tax_summary())
    canonical.setdefault("issues", [])
    if "no_valid_table_candidate" not in canonical["issues"]:
        canonical["issues"].append("no_valid_table_candidate")
    metadata["canonical_invoice"] = canonical
    return metadata


def _should_run_llm_extraction(metadata: Dict[str, Any]) -> bool:
    if _is_no_valid_table_candidate(metadata):
        return False
    markdown = metadata.get("semantic_markdown")
    return isinstance(markdown, str) and bool(markdown.strip())


class LegacyExtractionEngine(DocumentExtractionEngine):
    def extract(self, document_path: str, **kwargs) -> Dict[str, Any]:
        """
        Runs the legacy custom OCR and spatial reconstruction pipeline.
        
        Supported kwargs:
            reconstruct: bool
            reconstruct_mode: str
            extract: bool (whether to run LLM extraction)
            benchmark_mode: bool
            bypass_cache: bool
            filename: Optional[str]
        """
        reconstruct = kwargs.get("reconstruct", False)
        reconstruct_mode = kwargs.get("reconstruct_mode", settings.TSR_PRIMARY_ENGINE)
        run_llm_extraction = kwargs.get("extract", False)
        benchmark_mode = kwargs.get("benchmark_mode", False)
        bypass_cache = kwargs.get("bypass_cache", False)
        filename = kwargs.get("filename", None)

        # Read document bytes to calculate invoice MD5 and pre-validate image
        with open(document_path, "rb") as f:
            file_bytes = f.read()

        val_report = ImageValidator.validate_image(file_bytes)
        if not val_report["is_valid"]:
            logger.warning(f"[IMAGE VALIDATION FAILURE] File: {filename}, error: {val_report.get('error_message')}")
            raise ValueError(val_report.get("error_message", "Uploaded file is not a valid invoice image."))

        invoice_id = cache_service.compute_md5(file_bytes)
        processed_image_path = str(Path("datasets/debug") / f"{invoice_id}_ocr_corrected.png")

        logger.info(f"Processing invoice file: {filename or document_path}, computed invoice_id: {invoice_id}")

        # Check local cache unless bypass_cache is requested
        cached_result = None if bypass_cache else cache_service.get_cached_result(invoice_id)
        if cached_result:
            logger.info("OCR cache hit: reusing OCR blocks only")
            blocks = cached_result.get("blocks", [])
            cached_metadata = cached_result.get("metadata") if isinstance(cached_result.get("metadata"), dict) else {}
            metadata = {
                **cached_metadata,
                "blocks": blocks,
                "image_validation": val_report
            }
            if reconstruct or run_llm_extraction:
                logger.info("Cached reconstruction response disabled")
                logger.info("Running fresh reconstruction with current code")
                image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
                reconstruction_data = spatial_reconstruction.reconstruct_layout(
                    blocks,
                    debug=(not benchmark_mode),
                    reconstruct_mode=reconstruct_mode,
                    image=image,
                    benchmark_mode=benchmark_mode,
                )
                logger.info(f"Reconstruction keys from cache path: {reconstruction_data.keys()}")
                metadata.update(reconstruction_data)
                metadata = _apply_no_valid_table_response_defaults(
                    metadata,
                    invoice_id=invoice_id,
                    filename=filename,
                )

            # Check triggers for orientation recovery
            from services.orientation_recovery import should_attempt_orientation_recovery, run_orientation_recovery
            if should_attempt_orientation_recovery(metadata):
                logger.info("Triggering orientation recovery flow (cache hit)...")
                image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
                ocr_result = {
                    "text": cached_result.get("text", ""),
                    "blocks": blocks,
                    "metadata": cached_metadata
                }
                recovered_ocr, recovered_metadata = run_orientation_recovery(
                    original_image=image,
                    normal_payload={"ocr_result": ocr_result, "metadata": metadata},
                    reconstruct_mode=reconstruct_mode,
                    benchmark_mode=benchmark_mode,
                    processed_image_path=processed_image_path,
                )
                ocr_result = recovered_ocr
                metadata = recovered_metadata
                blocks = ocr_result.get("blocks", [])
                cached_metadata = ocr_result.get("metadata") if isinstance(ocr_result.get("metadata"), dict) else {}
                cache_service.save_result(invoice_id, ocr_result)

                if not (reconstruct or run_llm_extraction):
                    reconstruct_keys = [
                        "reconstructed_rows", "detected_table_rows", "structured_tables",
                        "columns_extracted", "semantic_markdown", "fast_fail", "fast_fail_reason",
                        "selected_table_available", "selected_table_id", "safe_for_erp",
                        "status_effective", "item_rows_clean", "scheme_rows", "credit_note_rows",
                        "invoice_totals", "llm_extraction", "quality_gate", "canonical_invoice"
                    ]
                    for key in reconstruct_keys:
                        metadata.pop(key, None)

            if run_llm_extraction and _should_run_llm_extraction(metadata):
                extractor = LLMExtractor()
                extraction_json = extractor.extract(metadata["semantic_markdown"])
                metadata["llm_extraction"] = extraction_json
            elif run_llm_extraction and _is_no_valid_table_candidate(metadata):
                metadata["llm_extraction"] = _safe_llm_extraction_defaults()
            metadata = normalize_orientation_metadata(metadata)
            metadata = _apply_no_valid_table_response_defaults(
                metadata,
                invoice_id=invoice_id,
                filename=filename,
            )

            response_payload = {
                "invoice_id": invoice_id,
                "cached": True,
                "text": ocr_result.get("text", "") if 'ocr_result' in locals() else cached_result.get("text", ""),
                "metadata": metadata,
            }
            diagnostics = write_upload_diagnostics(
                diagnostics_run_id=invoice_id,
                response_payload=response_payload,
                ocr_blocks=blocks,
                ocr_metadata=cached_metadata,
            )
            response_payload["metadata"]["diagnostics"] = diagnostics
            response_payload["metadata"]["diagnostics_run_id"] = diagnostics["diagnostics_run_id"]
            response_payload["metadata"]["artifacts"] = diagnostics["artifacts"]

            return response_payload

        # Cache miss path
        image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        ocr_result = ocr_engine.process_image(
            image,
            processed_image_path=processed_image_path,
            include_processed_image_data_url=True,
        )

        cache_service.save_result(invoice_id, ocr_result)

        blocks = ocr_result.get("blocks", [])
        ocr_metadata = ocr_result.get("metadata") if isinstance(ocr_result.get("metadata"), dict) else {}
        metadata = {
            **ocr_metadata,
            "blocks": blocks,
            "image_validation": val_report
        }
        if reconstruct or run_llm_extraction:
            logger.info("Cached reconstruction response disabled")
            logger.info("Running fresh reconstruction with current code")
            reconstruction_data = spatial_reconstruction.reconstruct_layout(
                blocks,
                debug=(not benchmark_mode),
                reconstruct_mode=reconstruct_mode,
                image=image,
                benchmark_mode=benchmark_mode,
            )
            logger.info(f"Reconstruction keys from fresh path: {reconstruction_data.keys()}")
            metadata.update(reconstruction_data)
            metadata = _apply_no_valid_table_response_defaults(
                metadata,
                invoice_id=invoice_id,
                filename=filename,
            )

        # Check triggers for orientation recovery
        from services.orientation_recovery import should_attempt_orientation_recovery, run_orientation_recovery
        if should_attempt_orientation_recovery(metadata):
            logger.info("Triggering orientation recovery flow (cache miss)...")
            recovered_ocr, recovered_metadata = run_orientation_recovery(
                original_image=image,
                normal_payload={"ocr_result": ocr_result, "metadata": metadata},
                reconstruct_mode=reconstruct_mode,
                benchmark_mode=benchmark_mode,
                processed_image_path=processed_image_path,
            )
            ocr_result = recovered_ocr
            metadata = recovered_metadata
            blocks = ocr_result.get("blocks", [])
            ocr_metadata = ocr_result.get("metadata") if isinstance(ocr_result.get("metadata"), dict) else {}
            cache_service.save_result(invoice_id, ocr_result)

            if not (reconstruct or run_llm_extraction):
                reconstruct_keys = [
                    "reconstructed_rows", "detected_table_rows", "structured_tables",
                    "columns_extracted", "semantic_markdown", "fast_fail", "fast_fail_reason",
                    "selected_table_available", "selected_table_id", "safe_for_erp",
                    "status_effective", "item_rows_clean", "scheme_rows", "credit_note_rows",
                    "invoice_totals", "llm_extraction", "quality_gate", "canonical_invoice"
                ]
                for key in reconstruct_keys:
                    metadata.pop(key, None)

        if run_llm_extraction and _should_run_llm_extraction(metadata):
            extractor = LLMExtractor()
            extraction_json = extractor.extract(metadata["semantic_markdown"])
            metadata["llm_extraction"] = extraction_json
        elif run_llm_extraction and _is_no_valid_table_candidate(metadata):
            metadata["llm_extraction"] = _safe_llm_extraction_defaults()
        metadata = normalize_orientation_metadata(metadata)
        metadata = _apply_no_valid_table_response_defaults(
            metadata,
            invoice_id=invoice_id,
            filename=filename,
        )

        response_payload = {
            "invoice_id": invoice_id,
            "cached": False,
            "text": ocr_result.get("text", ""),
            "metadata": metadata,
        }
        diagnostics = write_upload_diagnostics(
            diagnostics_run_id=invoice_id,
            response_payload=response_payload,
            ocr_blocks=blocks,
            ocr_metadata=ocr_metadata,
        )
        response_payload["metadata"]["diagnostics"] = diagnostics
        response_payload["metadata"]["diagnostics_run_id"] = diagnostics["diagnostics_run_id"]
        response_payload["metadata"]["artifacts"] = diagnostics["artifacts"]

        return response_payload
