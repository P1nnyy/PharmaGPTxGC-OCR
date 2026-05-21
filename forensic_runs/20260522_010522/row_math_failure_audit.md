# Cell-Level Row Math Failure Forensic Audit Report

Generated: 2026-05-22 01:05:22

This report provides a granular cell-level forensic audit of all row mathematical validation failures across the 7 baseline invoices. It categorizes the root causes of failures to identify system weaknesses.

## 1. Executive Summary & Telemetry

### Global Metrics
- **Total Failed Item Rows**: 47

### Failures by Invoice
| Invoice Filename | Failed Rows Count |
| :--- | :---: |
| 38e5c640-96c4-4268-b092-58de09e63216.JPG.json | 9 |
| 49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG.json | 9 |
| 7d4c3bb9-2c0b-4c75-b7d4-7c23244401bb.JPG.json | 4 |
| 7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json | 11 |
| 9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG.json | 8 |
| caf60269-bcd3-43e9-ad8c-2293eefbdbcb.JPG.json | 3 |
| cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG.json | 3 |

### Failures by Selected Topology
| Selected Table Topology | Failed Rows Count |
| :--- | :---: |
| document_graph_candidate | 3 |
| document_graph_fallback | 33 |
| heuristic_anchor | 11 |

### Failures by Cause Category
| Failure Cause Category | Failed Rows Count | % of Total |
| :--- | :---: | :---: |
| product column missing | 22 | 46.8% |
| cell assignment to wrong column | 11 | 23.4% |
| amount column missing | 8 | 17.0% |
| GST/discount affecting calculation | 4 | 8.5% |
| row is not a true item row | 1 | 2.1% |
| unknown | 1 | 2.1% |
| qty cell contains product/header/footer text | 0 | 0.0% |
| rate/amount columns merged | 0 | 0.0% |
| parser failure | 0 | 0.0% |

### Top 5 Repeated Failure Patterns
| Failure Pattern Description | Occurrences |
| :--- | :---: |
| amount column missing | Qty cell: '' | Amount cell: '' | 2 |
| product column missing | Qty cell: '2 212:21' | Amount cell: '223,38' | 1 |
| product column missing | Qty cell: '2 230.72' | Amount cell: '242.86' | 1 |
| GST/discount affecting calculation | Qty cell: '254.41' | Amount cell: '267.80' | 1 |
| product column missing | Qty cell: '327.84 9.0 9.0' | Amount cell: '345,09' | 1 |

## 2. Granular Failed Row Cell Export

---

### Failure #1: `graph_row_18` in `38e5c640-96c4-4268-b092-58de09e63216.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 2 212:21 | ['block_93', 'block_88'] |
| FREE QUANTITY | *empty* | None |
| RATE | 111.69 | ['block_86'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | 223,38 | ['block_87'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `111.69`
- **Parsed Actual Amount**: `22338.0`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `22338.0`

---

### Failure #2: `graph_row_19` in `38e5c640-96c4-4268-b092-58de09e63216.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 2 230.72 | ['block_104', 'block_100'] |
| FREE QUANTITY | *empty* | None |
| RATE | 121.43 | ['block_98'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | 242.86 | ['block_96'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `121.43`
- **Parsed Actual Amount**: `242.86`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `242.86`

---

### Failure #3: `graph_row_20` in `38e5c640-96c4-4268-b092-58de09e63216.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **GST/discount affecting calculation**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | NOVEGROW SHAMPOO TOOML  | ['block_106'] |
| QUANTITY (QTY) | 254.41 | ['block_116'] |
| FREE QUANTITY | *empty* | None |
| RATE | 267.80 | ['block_112'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | 267.80 | ['block_113'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `254.41`
- **Parsed Unit Rate**: `267.8`
- **Parsed Actual Amount**: `267.8`
- **Expected Amount Formula**: `254.41 * 267.8 = 68131.0`
- **Actual Row Amount**: `267.8`

---

### Failure #4: `graph_row_21` in `38e5c640-96c4-4268-b092-58de09e63216.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 327.84 9.0 9.0 | ['block_126'] |
| FREE QUANTITY | *empty* | None |
| RATE | 345,09 | ['block_123'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | 345,09 | ['block_124'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `34509.0`
- **Parsed Actual Amount**: `34509.0`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `34509.0`

---

### Failure #5: `graph_row_22` in `38e5c640-96c4-4268-b092-58de09e63216.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **amount column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | AROMED P 30049099 | *10ML 3958 | ['block_129'] |
| QUANTITY (QTY) | 356.15 | ['block_131'] |
| FREE QUANTITY | *empty* | None |
| RATE | 292.71 | ['block_133'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | *empty* | None |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `356.15`
- **Parsed Unit Rate**: `292.71`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `356.15 * 292.71 = 104248.67`
- **Actual Row Amount**: `n/a`

---

### Failure #6: `graph_row_23` in `38e5c640-96c4-4268-b092-58de09e63216.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **GST/discount affecting calculation**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | ALKEM LA 30049099 1 STRIPS 25442827 | ['block_139'] |
| QUANTITY (QTY) | 139.60 | ['block_145'] |
| FREE QUANTITY | *empty* | None |
| RATE | 146.95 | ['block_140'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | 146.95 | ['block_143'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `139.6`
- **Parsed Unit Rate**: `146.95`
- **Parsed Actual Amount**: `146.95`
- **Expected Amount Formula**: `139.6 * 146.95 = 20514.22`
- **Actual Row Amount**: `146.95`

---

### Failure #7: `graph_row_24` in `38e5c640-96c4-4268-b092-58de09e63216.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **amount column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 141.00 25 25 | ['block_155'] |
| FREE QUANTITY | *empty* | None |
| RATE | 148.42 | ['block_153'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | *empty* | None |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `148.42`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `n/a`

---

### Failure #8: `graph_row_25` in `38e5c640-96c4-4268-b092-58de09e63216.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **amount column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | ALKEMIA 30049099 | STRIPS 25442827 | ['block_158'] |
| QUANTITY (QTY) | 279.21 25 25 | ['block_164'] |
| FREE QUANTITY | *empty* | None |
| RATE | 146.95 | ['block_160'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | *empty* | None |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `146.95`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `n/a`

---

### Failure #9: `graph_row_26` in `38e5c640-96c4-4268-b092-58de09e63216.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **amount column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 250.73 2.5 2.5 | ['block_174'] |
| FREE QUANTITY | *empty* | None |
| RATE | 263.93 | ['block_171'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | *empty* | None |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `263.93`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `n/a`

---

### Failure #10: `graph_row_17` in `49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | *empty* | None |
| RATE | 250.64 | ['block_40'] |
| MRP | 328.13 | ['block_39'] |
| GST / TAX | 5.00 | ['block_43'] |
| AMOUNT | 250.64 | ['block_45'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `250.64`
- **Parsed Actual Amount**: `250.64`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `250.64`

---

### Failure #11: `graph_row_18` in `49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | *empty* | None |
| RATE | 159.89 | ['block_51'] |
| MRP | 209.86 | ['block_50'] |
| GST / TAX | 5.00 | ['block_54'] |
| AMOUNT | 159.89 | ['block_56'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `159.89`
- **Parsed Actual Amount**: `159.89`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `159.89`

---

### Failure #12: `graph_row_19` in `49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | *empty* | None |
| RATE | 95.76 | ['block_61'] |
| MRP | 125,69 | ['block_60'] |
| GST / TAX | 5.00 | ['block_64'] |
| AMOUNT | 191.52 | ['block_66'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `95.76`
- **Parsed Actual Amount**: `191.52`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `191.52`

---

### Failure #13: `graph_row_20` in `49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 2.750+.250 | ['block_71'] |
| FREE QUANTITY | *empty* | None |
| RATE | 178.32 | ['block_72'] |
| MRP | 234.05 | ['block_69'] |
| GST / TAX | 5.00 | ['block_76'] |
| AMOUNT | 178.32 | ['block_77'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `2.75`
- **Parsed Unit Rate**: `178.32`
- **Parsed Actual Amount**: `178.32`
- **Expected Amount Formula**: `2.75 * 178.32 = 490.38`
- **Actual Row Amount**: `178.32`

---

### Failure #14: `graph_row_21` in `49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 2.500+.500 MANKIN | ['block_83'] |
| FREE QUANTITY | *empty* | None |
| RATE | 71.34 | ['block_84'] |
| MRP | 93.64 | ['block_81'] |
| GST / TAX | 5.00 | ['block_86'] |
| AMOUNT | 196.19 | ['block_88'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `2.5`
- **Parsed Unit Rate**: `71.34`
- **Parsed Actual Amount**: `196.19`
- **Expected Amount Formula**: `2.5 * 71.34 = 178.35`
- **Actual Row Amount**: `196.19`

---

### Failure #15: `graph_row_22` in `49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | *empty* | None |
| RATE | 94.19 | ['block_93'] |
| MRP | 123.63 | ['block_92'] |
| GST / TAX | 5.00 | ['block_97'] |
| AMOUNT | 235.48 | ['block_98'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `94.19`
- **Parsed Actual Amount**: `235.48`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `235.48`

---

### Failure #16: `graph_row_23` in `49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | *empty* | None |
| RATE | 258.36 | ['block_103'] |
| MRP | 339.09 | ['block_102'] |
| GST / TAX | 5.00 | ['block_107'] |
| AMOUNT | 258.36 | ['block_109'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `258.36`
- **Parsed Actual Amount**: `258.36`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `258.36`

---

### Failure #17: `graph_row_24` in `49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 2.750+.250 MANKIN | ['block_116'] |
| FREE QUANTITY | *empty* | None |
| RATE | 258.36 | ['block_115'] |
| MRP | 339.09 | ['block_113'] |
| GST / TAX | 5.00 | ['block_119'] |
| AMOUNT | 258.36 | ['block_120'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `2.75`
- **Parsed Unit Rate**: `258.36`
- **Parsed Actual Amount**: `258.36`
- **Expected Amount Formula**: `2.75 * 258.36 = 710.49`
- **Actual Row Amount**: `258.36`

---

### Failure #18: `graph_row_25` in `49bdab61-6a62-469d-a942-5b41bf02eb6c.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | *empty* | None |
| RATE | 182.03 | ['block_125'] |
| MRP | 238.91 | ['block_124'] |
| GST / TAX | 5.00 | ['block_127'] |
| AMOUNT | 500.58 | ['block_128'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `182.03`
- **Parsed Actual Amount**: `500.58`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `500.58`

---

### Failure #19: `graph_row_11` in `7d4c3bb9-2c0b-4c75-b7d4-7c23244401bb.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **row is not a true item row**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | BANK NAME-Union Bank of India, PTK Bank Details SGST CGST | ['block_76', 'block_77', 'block_78', 'block_94'] |
| QUANTITY (QTY) | BEWO3AFA UN250128R 7/27 | ['block_89', 'block_90', 'block_103'] |
| FREE QUANTITY | *empty* | None |
| RATE | 44.47 44.47 | ['block_79', 'block_96'] |
| MRP | *empty* | None |
| GST / TAX | 28/11/2025 Batch Order DateOrder Date GST INVOICE | ['block_82', 'block_93', 'block_97', 'block_84'] |
| AMOUNT | 0.00 0.00 | ['block_80', 'block_95'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `None`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `n/a`

---

### Failure #20: `graph_row_13` in `7d4c3bb9-2c0b-4c75-b7d4-7c23244401bb.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | *empty* | None |
| RATE | 88.94 | ['block_119'] |
| MRP | *empty* | None |
| GST / TAX | Ack Date | ['block_121'] |
| AMOUNT | 0.00 | ['block_120'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `88.94`
- **Parsed Actual Amount**: `0.0`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `0.0`

---

### Failure #21: `graph_row_15` in `7d4c3bb9-2c0b-4c75-b7d4-7c23244401bb.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | FOR MAHAJAN MEDICAL AGENCIES  | ['block_122'] |
| QUANTITY (QTY) | 105.68 0.00323.05 0.00 62.29 0.00 89.29 0.00 113.22 0.00 2.502.502.502.502.502.502.502.50 | ['block_140', 'block_145', 'block_142', 'block_146', 'block_157'] |
| FREE QUANTITY | *empty* | None |
| RATE | *empty* | None |
| MRP | *empty* | None |
| GST / TAX | Rate Dis SGST  | ['block_139', 'block_154'] |
| AMOUNT | 5 9 | ['block_153'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `None`
- **Parsed Actual Amount**: `59.0`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `59.0`

---

### Failure #22: `graph_row_22` in `7d4c3bb9-2c0b-4c75-b7d4-7c23244401bb.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | 1892.54 | ['block_184'] |
| QUANTITY (QTY) | 488.8897.4468.92339.6689.29317.3362.29105.68323.05 | ['block_183'] |
| FREE QUANTITY | *empty* | None |
| RATE | *empty* | None |
| MRP | *empty* | None |
| GST / TAX | Amount  | ['block_182'] |
| AMOUNT | 1868.00 113.56 | ['block_181', 'block_185'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `None`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `n/a`

---

### Failure #23: `row_14` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **GST/discount affecting calculation**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | MACTOR 10 | ['block_53'] |
| QUANTITY (QTY) | 2 | ['block_48'] |
| FREE QUANTITY | 1*10 2 | ['block_51', 'block_54'] |
| RATE | 121.42 | ['block_46'] |
| MRP | 159.37 | ['block_45'] |
| GST / TAX | *empty* | None |
| AMOUNT | 364.26 | ['block_52'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `2.0`
- **Parsed Unit Rate**: `121.42`
- **Parsed Actual Amount**: `364.26`
- **Expected Amount Formula**: `2.0 * 121.42 = 242.84`
- **Actual Row Amount**: `364.26`

---

### Failure #24: `row_15` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | TELMIKIND BETA 50 | ['block_67'] |
| QUANTITY (QTY) | 3 | ['block_60'] |
| FREE QUANTITY | 1-10 2 | ['block_64', 'block_66'] |
| RATE | 40.20 | ['block_59'] |
| MRP | 52.76 | ['block_58'] |
| GST / TAX | *empty* | None |
| AMOUNT | 80.40 | ['block_65'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `3.0`
- **Parsed Unit Rate**: `40.2`
- **Parsed Actual Amount**: `80.4`
- **Expected Amount Formula**: `3.0 * 40.2 = 120.6`
- **Actual Row Amount**: `80.4`

---

### Failure #25: `row_16` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | TELVAS 20 TAB 1 X 15 | ['block_79'] |
| QUANTITY (QTY) | 4 | ['block_76'] |
| FREE QUANTITY | MIS 3 | ['block_78', 'block_80'] |
| RATE | 117.76 | ['block_72'] |
| MRP | 154.58 | ['block_71'] |
| GST / TAX | *empty* | None |
| AMOUNT | 235.56 | ['block_77'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `4.0`
- **Parsed Unit Rate**: `117.76`
- **Parsed Actual Amount**: `235.56`
- **Expected Amount Formula**: `4.0 * 117.76 = 471.04`
- **Actual Row Amount**: `235.56`

---

### Failure #26: `row_17` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | CILACAR 10 1 × 15 | ['block_92'] |
| QUANTITY (QTY) | 5 | ['block_89'] |
| FREE QUANTITY | 1440- | ['block_91'] |
| RATE | 42.48 | ['block_85'] |
| MRP | 55.76 | ['block_84'] |
| GST / TAX | *empty* | None |
| AMOUNT | 127,44 | ['block_90'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `5.0`
- **Parsed Unit Rate**: `42.48`
- **Parsed Actual Amount**: `12744.0`
- **Expected Amount Formula**: `5.0 * 42.48 = 212.4`
- **Actual Row Amount**: `12744.0`

---

### Failure #27: `row_18` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | RANTAC 150 1 4 30 | ['block_105'] |
| QUANTITY (QTY) | €. | ['block_101'] |
| FREE QUANTITY | 4.50+.50 1110 | ['block_103', 'block_104'] |
| RATE | 167.20 | ['block_97'] |
| MRP | 219.45 | ['block_96'] |
| GST / TAX | *empty* | None |
| AMOUNT | 334.40 | ['block_102'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `167.2`
- **Parsed Actual Amount**: `334.4`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `334.4`

---

### Failure #28: `row_19` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | NICARDIA RETARD 20MG | ['block_115'] |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | 1:30 | ['block_114'] |
| RATE | 38.67 | ['block_109'] |
| MRP | 50.75 | ['block_108'] |
| GST / TAX | *empty* | None |
| AMOUNT | 174.02 | ['block_113'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `38.67`
- **Parsed Actual Amount**: `174.02`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `174.02`

---

### Failure #29: `row_20` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | PRINCICAL TAB 1 7015 | ['block_126'] |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | 1:10= 2 | ['block_125', 'block_127'] |
| RATE | 110.63 | ['block_120'] |
| MRP | 145.19 | ['block_119'] |
| GST / TAX | *empty* | None |
| AMOUNT | 221.26 | ['block_124'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `110.63`
- **Parsed Actual Amount**: `221.26`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `221.26`

---

### Failure #30: `row_21` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | DERIVA CMS GEL | ['block_138'] |
| QUANTITY (QTY) | 19 | ['block_135'] |
| FREE QUANTITY | 15GM | ['block_136'] |
| RATE | 156.76 | ['block_131'] |
| MRP | 205.73 | ['block_130'] |
| GST / TAX | *empty* | None |
| AMOUNT | 313.52 | ['block_137'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `19.0`
- **Parsed Unit Rate**: `156.76`
- **Parsed Actual Amount**: `313.52`
- **Expected Amount Formula**: `19.0 * 156.76 = 2978.44`
- **Actual Row Amount**: `313.52`

---

### Failure #31: `row_22` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **GST/discount affecting calculation**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | 200ML ARISTOZYME SYP | ['block_149'] |
| QUANTITY (QTY) | 10 | ['block_145'] |
| FREE QUANTITY | *empty* | None |
| RATE | 354.33 | ['block_143'] |
| MRP | 465.00 | ['block_142'] |
| GST / TAX | *empty* | None |
| AMOUNT | 354.33 | ['block_148'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `10.0`
- **Parsed Unit Rate**: `354.33`
- **Parsed Actual Amount**: `354.33`
- **Expected Amount Formula**: `10.0 * 354.33 = 3543.3`
- **Actual Row Amount**: `354.33`

---

### Failure #32: `row_23` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | *empty* | None |
| RATE | 115.71 | ['block_153'] |
| MRP | 151.87 | ['block_152'] |
| GST / TAX | *empty* | None |
| AMOUNT | 115.71 | ['block_157'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `115.71`
- **Parsed Actual Amount**: `115.71`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `115.71`

---

### Failure #33: `row_24` in `7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json`
- **Selected Topology**: `heuristic_anchor`
- **Assigned Cause**: **amount column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | GST/2181.65*2.5+2.5%+54.55SGST+54.55CGST. | ['block_158'] |
| RATE | *empty* | None |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | *empty* | None |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `None`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `n/a`

---

### Failure #34: `graph_row_15` in `9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **amount column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | CGST 2.500 + SGST 2.500 | ['block_65'] |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | 17 | ['block_66'] |
| RATE | 0.00 | ['block_70'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | *empty* | None |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `0.0`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `n/a`

---

### Failure #35: `graph_row_16` in `9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | 39 | ['block_74'] |
| RATE | 0.00 | ['block_78'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | 3198.00 | ['block_84'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `0.0`
- **Parsed Actual Amount**: `3198.0`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `3198.0`

---

### Failure #36: `graph_row_18` in `9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 10  | ['block_108'] |
| FREE QUANTITY | *empty* | None |
| RATE | 126.99 | ['block_113'] |
| MRP | 36 160.00 0 | ['block_111'] |
| GST / TAX | *empty* | None |
| AMOUNT | 133,33 | ['block_121'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `10.0`
- **Parsed Unit Rate**: `126.99`
- **Parsed Actual Amount**: `13333.0`
- **Expected Amount Formula**: `10.0 * 126.99 = 1269.9`
- **Actual Row Amount**: `13333.0`

---

### Failure #37: `graph_row_19` in `9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 23 э | ['block_122', 'block_128'] |
| FREE QUANTITY | *empty* | None |
| RATE | 255.90 | ['block_129'] |
| MRP | 0 | ['block_127'] |
| GST / TAX | *empty* | None |
| AMOUNT | 259.28 | ['block_137'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `255.9`
- **Parsed Actual Amount**: `259.28`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `259.28`

---

### Failure #38: `graph_row_20` in `9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 33 2 | ['block_139', 'block_145'] |
| FREE QUANTITY | *empty* | None |
| RATE | 1001.34 | ['block_146'] |
| MRP | 0 | ['block_144'] |
| GST / TAX | *empty* | None |
| AMOUNT | 998.83 | ['block_154'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `1001.34`
- **Parsed Actual Amount**: `998.83`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `998.83`

---

### Failure #39: `graph_row_21` in `9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 35 0 12 | ['block_173', 'block_161'] |
| FREE QUANTITY | *empty* | None |
| RATE | 12 486.24 | ['block_162', 'block_163'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | 490.13 | ['block_171'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `12486.24`
- **Parsed Actual Amount**: `490.13`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `490.13`

---

### Failure #40: `graph_row_22` in `9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 60 0 22 | ['block_189', 'block_178'] |
| FREE QUANTITY | *empty* | None |
| RATE | 22 990.88 | ['block_179', 'block_180'] |
| MRP | 18 374.00 | ['block_193'] |
| GST / TAX | *empty* | None |
| AMOUNT | 990.88 | ['block_188'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `22990.88`
- **Parsed Actual Amount**: `990.88`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `990.88`

---

### Failure #41: `graph_row_23` in `9ed2543c-2e03-42ea-9fec-c68ee8c39625.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 0 1 | ['block_194'] |
| FREE QUANTITY | *empty* | None |
| RATE | 309.73 | ['block_195'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | 325.21 | ['block_203'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `309.73`
- **Parsed Actual Amount**: `325.21`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `325.21`

---

### Failure #42: `graph_row_5` in `caf60269-bcd3-43e9-ad8c-2293eefbdbcb.JPG.json`
- **Selected Topology**: `document_graph_candidate`
- **Assigned Cause**: **unknown**
- **Raw Validation Status**: `FAIL missing_semantic_columns:rate`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | SCHEME | ['block_30'] |
| QUANTITY (QTY) | *empty* | None |
| FREE QUANTITY | *empty* | None |
| RATE | *empty* | None |
| MRP | *empty* | None |
| GST / TAX | 0.00  | ['block_38'] |
| AMOUNT | 0.00 | ['block_37'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `None`
- **Parsed Actual Amount**: `0.0`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `0.0`

---

### Failure #43: `graph_row_14` in `caf60269-bcd3-43e9-ad8c-2293eefbdbcb.JPG.json`
- **Selected Topology**: `document_graph_candidate`
- **Assigned Cause**: **amount column missing**
- **Raw Validation Status**: `FAIL missing_semantic_columns:rate`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 6.00 0.00 2.502.502.502.502.50 | ['block_83', 'block_93', 'block_98'] |
| FREE QUANTITY | *empty* | None |
| RATE | *empty* | None |
| MRP | *empty* | None |
| GST / TAX | 0 0 Dis1 Dis2 SGST | ['block_88', 'block_82'] |
| AMOUNT | *empty* | None |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `None`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `n/a`

---

### Failure #44: `graph_row_19` in `caf60269-bcd3-43e9-ad8c-2293eefbdbcb.JPG.json`
- **Selected Topology**: `document_graph_candidate`
- **Assigned Cause**: **product column missing**
- **Raw Validation Status**: `FAIL missing_semantic_columns:rate`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | *empty* | None |
| QUANTITY (QTY) | 283.20154.3677.01155.32140.05118.65 | ['block_113'] |
| FREE QUANTITY | *empty* | None |
| RATE | *empty* | None |
| MRP | *empty* | None |
| GST / TAX | 928.59 Amount | ['block_112', 'block_111'] |
| AMOUNT | 52.8821.9021.900.00 | ['block_114'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `None`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `n/a`

---

### Failure #45: `graph_row_15` in `cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | CNDERO MET 2.5/1000 M 30049099 10 S LUPIN UB02123  | ['block_33', 'block_37'] |
| QUANTITY (QTY) | 135.16 07/27 | ['block_40'] |
| FREE QUANTITY | *empty* | None |
| RATE | 168.95 0 | ['block_42', 'block_43'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | 270.32 | ['block_45'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `168.95`
- **Parsed Actual Amount**: `270.32`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `270.32`

---

### Failure #46: `graph_row_16` in `cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **cell assignment to wrong column**
- **Raw Validation Status**: `FAIL (formula: math_failed)`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | MANKIN OUFZY045-  | ['block_46'] |
| QUANTITY (QTY) | 2.00 0.16 64.13 05/27 | ['block_39', 'block_48'] |
| FREE QUANTITY | *empty* | None |
| RATE | 84.16 90 | ['block_49', 'block_50'] |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | 118.00 | ['block_52'] |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `84.169`
- **Parsed Actual Amount**: `118.0`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `118.0`

---

### Failure #47: `graph_row_23` in `cb07d17e-fd1c-4ff6-8b05-7b699189485d.JPG.json`
- **Selected Topology**: `document_graph_fallback`
- **Assigned Cause**: **amount column missing**
- **Raw Validation Status**: `FAIL incomplete_qty_rate_amount_values`

#### Cell Level Texts & Mappings
| Column Semantic | Cell Text | Mapped Block IDs |
| :--- | :--- | :--- |
| PRODUCT / DRUG | 368.90 SGST 2.5%: SGST 61 :  9.22 CGST 2.5%: CGST 6% : | ['block_70', 'block_71', 'block_76', 'block_72', 'block_78'] |
| QUANTITY (QTY) | 9.22 IGST 5% : IGST 12% : | ['block_74', 'block_79'] |
| FREE QUANTITY | *empty* | None |
| RATE | *empty* | None |
| MRP | *empty* | None |
| GST / TAX | *empty* | None |
| AMOUNT | *empty* | None |

#### Parsed Values & Mathematical Audit
- **Parsed Billed Quantity**: `None`
- **Parsed Unit Rate**: `None`
- **Parsed Actual Amount**: `None`
- **Expected Amount Formula**: `n/a`
- **Actual Row Amount**: `n/a`