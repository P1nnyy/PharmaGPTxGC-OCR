from __future__ import annotations

from typing import Any, Dict

from services.layout_pipeline.canonical_invoice import build_canonical_invoice
from services.layout_pipeline.footer_rescue import diagnose_footer_rescue
from services.layout_pipeline.layout_profile import classify_layout_profile
from services.layout_pipeline.quality_gate import evaluate_invoice_quality
from services.layout_pipeline.row_math_repair import diagnose_row_math_repairs


def attach_invoice_diagnostics(result: Dict[str, Any], invoice_id: str = "unknown") -> Dict[str, Any]:
    if not isinstance(result, dict):
        return result

    resolved_invoice_id = invoice_id
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    if not resolved_invoice_id or resolved_invoice_id == "unknown":
        resolved_invoice_id = metadata.get("invoice_id") or "unknown"

    canonical_invoice = build_canonical_invoice(result, invoice_id=resolved_invoice_id)
    footer_rescue_report = diagnose_footer_rescue(canonical_invoice, result)
    row_math_repair_report = diagnose_row_math_repairs(canonical_invoice, result)
    layout_profile_report = classify_layout_profile(canonical_invoice, result)
    canonical_invoice.layout_profile = layout_profile_report
    result["row_math_repair"] = row_math_repair_report
    quality_gate_report = evaluate_invoice_quality(canonical_invoice, result)

    result["canonical_invoice"] = canonical_invoice.to_dict()
    result["layout_profile"] = layout_profile_report
    result["footer_rescue"] = footer_rescue_report
    result["row_math_repair"] = row_math_repair_report
    result["quality_gate"] = quality_gate_report
    result["status_effective"] = quality_gate_report["status"]
    result["safe_for_erp"] = quality_gate_report["safe_for_erp"]

    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    diagnostics.update({
        "layout_profile": layout_profile_report,
        "footer_rescue": footer_rescue_report,
        "row_math_repair": row_math_repair_report,
        "quality_gate": quality_gate_report,
    })
    result["diagnostics"] = diagnostics
    return result
