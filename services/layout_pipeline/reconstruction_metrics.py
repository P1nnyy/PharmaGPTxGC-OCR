from typing import Any, Dict


def _compute_tsr_confidence(table_regions) -> float:
    """
    Evaluate aggregate TSR output quality to decide if PPStructure topology is trustworthy.
    Returns 0.0-1.0 confidence score.

    Signals checked:
    - At least one table detected
    - Tables have reasonable cell counts
    - topology_confidence values from the engine are acceptable
    """
    if not table_regions:
        return 0.0

    confidences = [tr.topology_confidence for tr in table_regions]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    # Check for degenerate tables (tables with zero cells)
    total_cells = sum(len(tr.cells) for tr in table_regions)
    if total_cells == 0:
        return 0.0

    # A single table with very few cells on a full invoice is suspicious
    if len(table_regions) == 1 and total_cells < 3:
        avg_confidence *= 0.5

    return round(avg_confidence, 3)


def _invoice_footer_tax_source_counts(invoice_reconciliation: Dict[str, Any]) -> Dict[str, int]:
    footer_labels = {
        "parsed_subtotal",
        "discount",
        "roundoff",
        "cr_dr_note",
        "parsed_grand_total",
    }
    tax_labels = {"sgst", "cgst", "igst"}
    footer_rows = set()
    tax_rows = set()

    for source_map in (
        invoice_reconciliation.get("sources") or {},
        invoice_reconciliation.get("ignored_sources") or {},
    ):
        for label, source_or_sources in source_map.items():
            sources = source_or_sources if isinstance(source_or_sources, list) else [source_or_sources]
            for source in sources:
                if not isinstance(source, dict):
                    continue
                row_key = (source.get("table_id"), source.get("row_id"))
                if not row_key[0] or not row_key[1]:
                    continue
                if label in tax_labels:
                    tax_rows.add(row_key)
                elif label in footer_labels:
                    footer_rows.add(row_key)

    return {
        "footer_rows_count": len(footer_rows),
        "tax_rows_count": len(tax_rows),
    }
