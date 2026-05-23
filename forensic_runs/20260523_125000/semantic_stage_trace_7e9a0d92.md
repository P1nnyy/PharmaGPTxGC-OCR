# Forensic Semantic Stage Trace - Invoice 7e9a0d92

This trace analyzes the semantic column classification, stabilization, and overwrites for the table columns of invoice `7e9a0d92`.

---

## 1. Trace of final_column_semantics Lifecycle

We traced all places in the codebase where column semantics are defined, populated, cached, or overwritten:

1. **Creation/Classification**: 
   * [semantic_column_classifier.py](file:///Users/pranavgupta/PharmaGPTxGC-OCR/services/layout_pipeline/semantic_column_classifier.py) inside `analyze_table_columns()`. This is where column profiles are built, scores are evaluated, and `final_column_semantics[col_id] = best_type` is populated.
2. **Reconstruction Pipeline & Stabilization**:
   * [spatial_reconstruction.py](file:///Users/pranavgupta/PharmaGPTxGC-OCR/services/spatial_reconstruction.py):
     * **First Pass (Lines 1548-1570)**: It runs `enrich_region_metadata(tr)` on each table region, extracts `inferred_summary["final_column_semantics"]`, and caches it in `final_column_semantics[tr.table_id]`.
     * **TSR Anchor Split / Repair Loop (Lines 1581-1649)**: If the table matches undersegmentation heuristics (e.g. missing `quantity`, `rate`, or `amount` as per `_semantic_repair_trigger`), it invokes `repair_undersegmented_table_with_anchors()`. If this mutates the table, it clears the old `semantic_results` and `final_column_semantics` maps and **re-evaluates** `classifier.enrich_region_metadata()` over the newly split columns (`anchor_col_0`, `anchor_col_1`, etc.).
     * **Telemetry & Save**: Stores `final_column_semantics` in the output `metrics["final_column_semantics"]` (line 2080) and `semantic_debug["final_column_semantics"]` (line 1800).
3. **Anchor Semantic Assignment Path**:
   * [column_anchor_detector.py](file:///Users/pranavgupta/PharmaGPTxGC-OCR/services/layout_pipeline/column_anchor_detector.py):
     * `_semantic_repair_trigger()` reads the cached `final_column_semantics` from the cached dictionary:
       ```python
       final_semantics = inferred.get("final_column_semantics", {})
       ```
       If the types in the table are just `{"product", "amount"}` or `{"product"}` or `{"amount"}`, it triggers the undersegmented repair, replacing the columns with `anchor_col_0`, `anchor_col_1`, etc., which are then re-evaluated by the classifier.

No other scripts or components in the pipeline modify or overwrite `final_column_semantics`.

---

## 2. Stage-by-Stage Semantics for Invoice 7e9a0d92

The visual layout of invoice `7e9a0d92` consists of the primary table `heuristic_region_7`. Below are the semantic stages resolved by our newly implemented sequential/pack classifier rules:

### Stage 1: Raw Classifier Output
During the first pass (or fallback), the classifier scores columns based on visual value densities and headers:
* `col_0` (Header: "S.No" visually) -> Classified as `serial` (sequential numbers `2, 3, 4, 5`).
* `col_1` (Header: "Particulars" visually) -> Classified as `product`.
* `col_2` (Header: "PACK") -> Classified as `pack`.
* `col_3` (Header: "QTY") -> Classified as `quantity`.

### Stage 2: Post-Quarantine Output
* Cells with non-conforming numeric formats in whitelisted columns (like MRP or Rate) are quarantined (flagged as `semantic_outlier = True` with `expected_numeric_column_but_text_found`), but visual texts are preserved for downstream diagnostics.

### Stage 3: Post-Anchor Split / Repair Output
Because the primary table was undersegmented, the anchor repair engine generated geometry-split anchor columns:
* `anchor_product` (leftmost empty column) -> `"unknown"`
* `anchor_col_0` -> `"serial"`
* `anchor_col_1` -> `"quantity"`
* `anchor_col_2` -> `"product"`
* `anchor_col_3` -> `"batch"`
* `anchor_col_4` -> `"expiry"`
* `anchor_col_5` -> `"hsn"`
* `anchor_col_6` -> `"mrp"`
* `anchor_col_7` -> `"rate"`
* `anchor_col_11` -> `"amount"`

### Stage 4: Saved Metadata
The final mapped semantics saved in `results/7e9a0d92-49b0-40e4-bc0d-7577f52ea29d.JPG.json` are:
```json
{
  "heuristic_region_7": {
    "anchor_col_0": "serial",
    "anchor_col_1": "quantity",
    "anchor_col_2": "product",
    "anchor_col_3": "batch",
    "anchor_col_4": "expiry",
    "anchor_col_5": "hsn",
    "anchor_col_6": "mrp",
    "anchor_col_7": "rate",
    "anchor_col_8": "unknown",
    "anchor_col_9": "unknown",
    "anchor_col_10": "unknown",
    "anchor_col_11": "amount"
  }
}
```

---

## 3. Detailed Column Audit: anchor_col_0 & anchor_col_1

| Metric / Field | `anchor_col_0` | `anchor_col_1` |
| :--- | :--- | :--- |
| **Visual Header Text** | `S.` (part of merged header block `"S. Qty. Pack Product"`) | `Qty.` (part of merged header block `"S. Qty. Pack Product"`) |
| **Sample Body Cell Texts** | `'2'`, `'3'`, `'4'`, `'5'` | `'1*10 2'`, `'1-10 2'`, `'MIS 3'`, `'1440-'` |
| **Classifier Semantic** | `serial` | `quantity` |
| **Final Semantic** | `serial` | `quantity` |
| **Semantic Overwrite Point** | N/A (Remains `serial` at all stages) | N/A (Remains `quantity` at all stages) |

---

## 4. Key Discovery & Interpretation
* The new classification logic successfully assigned `anchor_col_0` to `"serial"` and `anchor_col_1` to `"quantity"`.
* However, the Qty and Pack columns visually merged into `anchor_col_1` during anchor repair (containing cell values like `'1-10 2'`). 
* Because `"1-10 2"` is compound, the `qty_parser` cannot extract a plain quantity, defaulting to `billed_qty = 0`, which subsequently triggers row math validation failures (`0 * rate != amount`).
