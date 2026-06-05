# Table Routing Boundary Audit

## Executive Summary

The current failure is likely **reconstruction fragmentation**. No full-width candidate table region encompassing the entire medicine table exists before routing. The medicine table has already been split horizontally or vertically in `row_clustering.py` or `heuristic_tsr.py` prior to the routing step.

## Per-Invoice Decision

| filename | selected table id | selected rows x cols | selected x coverage | best full-width candidate id | best candidate rows x cols | best candidate x coverage | case label | conclusion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG | heuristic_region_12 | 7x13 | 0.728 | None | 0x0 | 0.0 | CASE_B_RECONSTRUCTION_FRAGMENTATION | No full-width candidate region exists. Table is fragmented before routing. |
| cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG | heuristic_region_6 | 2x6 | 0.7596 | None | 0x0 | 0.0 | CASE_B_RECONSTRUCTION_FRAGMENTATION | No full-width candidate region exists. Table is fragmented before routing. |

## All Candidate Table Regions

### Invoice: 9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG

| candidate table id | rows x cols | x coverage | non-empty cells | labels | routing score | score profile | selected? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| heuristic_region_0 | 1x3 | 0.7597 | 3/3 | collapsed_slice | -362.0 | low_signal_candidate; penalties=region_type_totals,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_1 | 1x3 | 0.4594 | 3/3 | collapsed_slice | -542.0 | low_signal_candidate; penalties=region_type_header,single_row_without_product_evidence,no_product_evidence_non_medicine_region,invoice_metadata_without_products | No |
| heuristic_region_2 | 8x1 | 0.7575 | 8/8 | collapsed_slice | 52.0 | rows_ge_2,rows_ge_5,batch_patterns,hsn_patterns,anchor_repairability_product_table_potential; penalties=no_product_evidence_non_medicine_region,bank_metadata | No |
| heuristic_region_3 | 1x5 | 0.6986 | 5/5 | collapsed_slice | -251.0 | columns_ge_4,batch_patterns,hsn_patterns; penalties=region_type_header,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_4 | 1x1 | 0.0679 | 1/1 | collapsed_slice | -388.0 | batch_patterns; penalties=region_type_header,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_5 | 2x1 | 0.7353 | 2/2 | collapsed_slice | -1548.0 | rows_ge_2; penalties=footer_phrase_hits,tiny_footer_summary_table,one_or_two_cell_summary_table,summary_like_rows,region_type_totals,footer_without_product_evidence | No |
| heuristic_region_6 | 1x2 | 0.5389 | 1/2 | collapsed_slice | -224.0 | numeric_diversity; penalties=single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_7 | 3x12 | 0.7364 | 21/36 | collapsed_slice, possible_footer_or_tax_slice | 583.0 | rows_ge_2,columns_ge_4,columns_ge_8,numeric_diversity,medicine_table_without_footer_phrases | No |
| heuristic_region_8 | 1x5 | 0.6424 | 5/5 | unknown | -1283.0 | columns_ge_4; penalties=footer_phrase_hits,tiny_footer_summary_table,summary_like_rows,region_type_totals,single_row_without_product_evidence,footer_without_product_evidence | No |
| heuristic_region_9 | 1x2 | 0.3699 | 1/2 | collapsed_slice | -271.0 | low_signal_candidate; penalties=single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_10 | 1x4 | 0.3254 | 4/4 | collapsed_slice | 107.0 | columns_ge_4,hsn_patterns,numeric_diversity,medicine_table_without_footer_phrases; penalties=single_row_without_product_evidence | No |
| heuristic_region_11 | 1x9 | 0.337 | 9/9 | collapsed_slice | 38.0 | columns_ge_4,columns_ge_8,numeric_diversity; penalties=single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_12 | 7x13 | 0.728 | 54/91 | collapsed_slice | 1024.143 | rows_ge_2,rows_ge_5,columns_ge_4,columns_ge_8,product_like_rows,hsn_patterns | **Yes** |
| heuristic_region_13 | 1x8 | 0.2859 | 8/8 | collapsed_slice | 28.0 | columns_ge_4,columns_ge_8,numeric_diversity; penalties=single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_14 | 1x8 | 0.6068 | 8/8 | collapsed_slice | -92.0 | columns_ge_4,columns_ge_8,numeric_diversity; penalties=region_type_totals,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_15 | 1x1 | 0.307 | 1/1 | collapsed_slice | -396.0 | low_signal_candidate; penalties=region_type_header,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_16 | 6x2 | 0.3092 | 9/12 | collapsed_slice | 302.0 | rows_ge_2,rows_ge_5,batch_patterns,numeric_diversity,anchor_repairability_product_table_potential; penalties=no_product_evidence_non_medicine_region | No |
| heuristic_region_17 | 2x2 | 0.2892 | 4/4 | collapsed_slice | -209.0 | rows_ge_2; penalties=region_type_totals,no_product_evidence_non_medicine_region | No |
| heuristic_region_18 | 1x1 | 0.1146 | 1/1 | collapsed_slice | -1516.0 | low_signal_candidate; penalties=footer_phrase_hits,tiny_footer_summary_table,one_or_two_cell_summary_table,summary_like_rows,single_row_without_product_evidence,footer_without_product_evidence | No |
| heuristic_region_19 | 1x1 | 0.317 | 1/1 | collapsed_slice | -396.0 | low_signal_candidate; penalties=region_type_totals,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_20 | 1x1 | 0.0895 | 1/1 | collapsed_slice | -276.0 | low_signal_candidate; penalties=single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |

### Invoice: cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG

| candidate table id | rows x cols | x coverage | non-empty cells | labels | routing score | score profile | selected? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| heuristic_region_0 | 1x1 | 0.6002 | 1/1 | collapsed_slice | -788.0 | batch_patterns; penalties=single_row_without_product_evidence,no_product_evidence_non_medicine_region,ifsc_pattern,bank_metadata | No |
| heuristic_region_1 | 1x1 | 0.641 | 1/1 | collapsed_slice | -392.0 | low_signal_candidate; penalties=region_type_header,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_2 | 2x2 | 0.5735 | 3/4 | collapsed_slice, possible_footer_or_tax_slice | -2.0 | rows_ge_2,numeric_diversity; penalties=no_product_evidence_non_medicine_region | No |
| heuristic_region_3 | 1x3 | 0.7627 | 3/3 | collapsed_slice, possible_footer_or_tax_slice | -1512.0 | low_signal_candidate; penalties=footer_phrase_hits,tiny_footer_summary_table,summary_like_rows,region_type_totals,single_row_without_product_evidence,footer_without_product_evidence | No |
| heuristic_region_4 | 4x3 | 0.7618 | 9/12 | collapsed_slice, possible_footer_or_tax_slice | -533.5 | rows_ge_2; penalties=footer_phrase_hits,footer_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_5 | 1x2 | 0.2165 | 2/2 | collapsed_slice | -349.0 | numeric_diversity; penalties=region_type_totals,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_6 | 2x6 | 0.7596 | 12/12 | collapsed_slice | 566.0 | rows_ge_2,columns_ge_4,batch_patterns,expiry_patterns,hsn_patterns,numeric_diversity | **Yes** |
| heuristic_region_7 | 1x2 | 0.6082 | 2/2 | collapsed_slice | -379.0 | low_signal_candidate; penalties=region_type_header,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_8 | 2x3 | 0.6788 | 3/6 | collapsed_slice | -95.0 | rows_ge_2; penalties=no_product_evidence_non_medicine_region | No |
| heuristic_region_9 | 1x2 | 0.6854 | 2/2 | collapsed_slice | -371.0 | batch_patterns; penalties=region_type_header,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_10 | 1x2 | 0.687 | 2/2 | collapsed_slice | -243.0 | hsn_patterns; penalties=single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_11 | 1x3 | 0.7804 | 3/3 | collapsed_slice | -514.0 | batch_patterns,expiry_patterns; penalties=region_type_header,single_row_without_product_evidence,no_product_evidence_non_medicine_region,invoice_metadata_without_products | No |
| heuristic_region_12 | 2x1 | 0.5781 | 2/2 | collapsed_slice | -96.0 | rows_ge_2,batch_patterns,hsn_patterns; penalties=no_product_evidence_non_medicine_region | No |
| heuristic_region_13 | 1x1 | 0.1225 | 1/1 | collapsed_slice, possible_footer_or_tax_slice | -396.0 | low_signal_candidate; penalties=region_type_totals,single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |
| heuristic_region_14 | 1x2 | 0.7573 | 2/2 | collapsed_slice, possible_footer_or_tax_slice | -55.0 | batch_patterns,expiry_patterns,hsn_patterns,anchor_repairability_product_table_potential; penalties=single_row_without_product_evidence,no_product_evidence_non_medicine_region | No |

## Final Recommendation

### Recommended Action: Patch `row_clustering.py` / `heuristic_tsr.py` reconstruction
Since no full-width table candidate exists before routing, the table is already fragmented. We must:
1. Fix row grouping logic in `row_clustering.py` to prevent horizontal splitting when small page skew is present.
2. Prevent over-segmentation in `heuristic_tsr.py` when consecutive rows have slight classification variations (e.g., intermediate 'Unknown' rows).

## Evidence

- Target Images processed:
  1. `test_images/9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG`
  2. `test_images/cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG`
- The audit evaluated candidate TableRegions generated dynamically using production geometry extraction, skew normalization, heuristic TSR detection, cell mapping, and multiline merging.
- Full JSON results are saved in `scratch/table_routing_boundary_audit_results.json`.