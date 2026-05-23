# Wrong Column Assignment Audit

- Generated at: `2026-05-23T11:33:28`
- Forensic audit inputs: `1` from `forensic_runs`
- Benchmark JSON inputs: `0` from `scripts/benchmarks/outputs`
- Total wrong-column failures: **11**

## Summary

| Metric | Value |
| :--- | :--- |
| Total wrong-column failures | 11 |

## Failures By Invoice

| Invoice | Failures |
| :--- | :--- |
| 7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json | 7 |
| 7d4c3bb9-2c0b-4c75-b7d4-7c23244401bb.JPG.json | 2 |
| cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG.json | 2 |

## Failures By Selected Topology

| Selected topology | Failures |
| :--- | :--- |
| heuristic_anchor | 7 |
| document_graph_fallback | 4 |

## Failures By Confusion Pattern

| Confusion pattern | Failures |
| :--- | :--- |
| unknown wrong-column pattern | 7 |
| quantity missing but rate/amount present | 2 |
| product received numeric-only value | 1 |
| amount decimal-comma normalization issue | 1 |

## Top Repeated Text Patterns

| Cell text | Occurrences |
| :--- | :--- |
| FOR MAHAJAN MEDICAL AGENCIES | 1 |
| 105.68 0.00323.05 0.00 62.29 0.00 89.29 0.00 113.22 0.00 2.502.502.502.502.502.502.502.50 | 1 |
| Rate Dis SGST | 1 |
| 5 9 | 1 |
| 1892.54 | 1 |
| 488.8897.4468.92339.6689.29317.3362.29105.68323.05 | 1 |
| Amount | 1 |
| 1868.00 113.56 | 1 |
| TELMIKIND BETA 50 | 1 |
| 3 | 1 |
| 1-10 2 | 1 |
| 40.20 | 1 |
| 52.76 | 1 |
| 80.40 | 1 |
| TELVAS 20 TAB 1 X 15 | 1 |
| 4 | 1 |
| MIS 3 | 1 |
| 117.76 | 1 |
| 154.58 | 1 |
| 235.56 | 1 |

## Pattern Examples

### unknown wrong-column pattern

Failures: **7**

| Invoice filename | Selected topology source | Row ID | Product cell text | Qty cell text | Free qty cell text | Rate cell text | MRP cell text | GST cell text | Amount cell text | Parsed qty | Parsed rate | Parsed amount | Mapped block IDs | Short diagnosis |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 7d4c3bb9-2c0b-4c75-b7d4-7c23244401bb.JPG.json | document_graph_fallback | graph_row_15 | FOR MAHAJAN MEDICAL AGENCIES | 105.68 0.00323.05 0.00 62.29 0.00 89.29 0.00 113.22 0.00 2.502.502.502.502.502.502.502.50 | n/a | n/a | n/a | Rate Dis SGST | 5 9 | n/a | n/a | 59.0 | amount: block_153<br>free_qty: []<br>gst: block_139, block_154<br>mrp: []<br>product: block_122<br>qty: block_140, block_145, block_142, block_146, block_157<br>rate: [] | Wrong-column cause found, but available cell text does not match a named confusion rule. |
| 7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json | heuristic_anchor | row_15 | TELMIKIND BETA 50 | 3 | 1-10 2 | 40.20 | 52.76 | n/a | 80.40 | 3.0 | 40.2 | 80.4 | amount: block_65<br>free_qty: block_64, block_66<br>gst: []<br>mrp: block_58<br>product: block_67<br>qty: block_60<br>rate: block_59 | Wrong-column cause found, but available cell text does not match a named confusion rule. |
| 7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json | heuristic_anchor | row_16 | TELVAS 20 TAB 1 X 15 | 4 | MIS 3 | 117.76 | 154.58 | n/a | 235.56 | 4.0 | 117.76 | 235.56 | amount: block_77<br>free_qty: block_78, block_80<br>gst: []<br>mrp: block_71<br>product: block_79<br>qty: block_76<br>rate: block_72 | Wrong-column cause found, but available cell text does not match a named confusion rule. |

### quantity missing but rate/amount present

Failures: **2**

| Invoice filename | Selected topology source | Row ID | Product cell text | Qty cell text | Free qty cell text | Rate cell text | MRP cell text | GST cell text | Amount cell text | Parsed qty | Parsed rate | Parsed amount | Mapped block IDs | Short diagnosis |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json | heuristic_anchor | row_19 | NICARDIA RETARD 20MG | n/a | 1:30 | 38.67 | 50.75 | n/a | 174.02 | n/a | 38.67 | 174.02 | amount: block_113<br>free_qty: block_114<br>gst: []<br>mrp: block_108<br>product: block_115<br>qty: []<br>rate: block_109 | Rate and amount are present but no quantity cell was assigned. |
| 7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json | heuristic_anchor | row_20 | PRINCICAL TAB 1 7015 | n/a | 1:10= 2 | 110.63 | 145.19 | n/a | 221.26 | n/a | 110.63 | 221.26 | amount: block_124<br>free_qty: block_125, block_127<br>gst: []<br>mrp: block_119<br>product: block_126<br>qty: []<br>rate: block_120 | Rate and amount are present but no quantity cell was assigned. |

### amount decimal-comma normalization issue

Failures: **1**

| Invoice filename | Selected topology source | Row ID | Product cell text | Qty cell text | Free qty cell text | Rate cell text | MRP cell text | GST cell text | Amount cell text | Parsed qty | Parsed rate | Parsed amount | Mapped block IDs | Short diagnosis |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json | heuristic_anchor | row_17 | CILACAR 10 1 × 15 | 5 | 1440- | 42.48 | 55.76 | n/a | 127,44 | 5.0 | 42.48 | 12744.0 | amount: block_90<br>free_qty: block_91<br>gst: []<br>mrp: block_84<br>product: block_92<br>qty: block_89<br>rate: block_85 | Decimal comma appears in a numeric cell involved in the wrong-column failure. |

### product received numeric-only value

Failures: **1**

| Invoice filename | Selected topology source | Row ID | Product cell text | Qty cell text | Free qty cell text | Rate cell text | MRP cell text | GST cell text | Amount cell text | Parsed qty | Parsed rate | Parsed amount | Mapped block IDs | Short diagnosis |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 7d4c3bb9-2c0b-4c75-b7d4-7c23244401bb.JPG.json | document_graph_fallback | graph_row_22 | 1892.54 | 488.8897.4468.92339.6689.29317.3362.29105.68323.05 | n/a | n/a | n/a | Amount | 1868.00 113.56 | n/a | n/a | n/a | amount: block_181, block_185<br>free_qty: []<br>gst: block_182<br>mrp: []<br>product: block_184<br>qty: block_183<br>rate: [] | Product column contains only a numeric value. |

## Notes

- This report is diagnostic-only.
- No extraction, topology selection, row validation, or reconciliation code is modified by the audit generator.
- Confusion patterns are assigned by deterministic cell-text rules in `scratch/parse_wrong_columns.py`.
