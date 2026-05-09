# PharmaGPTxGC SQA Verification & Debugging Workspace

This dedicated workspace provides an isolated sandbox environment to evaluate, visualize, and benchmark the active OCR and layout reconstruction pipeline without bloating or polluting the production codebase.

## 1. Directory Structure

```text
verification/
├── dashboards/              # Interactive validation dashboards
├── comparisons/             # OCR JSON structural comparisons
│   └── ocr_comparison_report.md
├── debug_outputs/           # Transient raw data outputs
├── visualizations/          # OpenCV-rendered coordinate and TSR cell mappings
├── benchmark_reports/       # Financial math and final SQA summaries
│   ├── financial_validation_report.md
│   └── consolidated_report.md
├── scripts/                 # Core verification scripts
│   ├── compare_ocr_results.py
│   ├── render_layout_debug.py
│   ├── validate_invoice_math.py
│   └── run_full_verification.py
└── README.md                # This documentation
```

---

## 2. Getting Started & Script Usage

To run the full suite at once:
```bash
python3 verification/scripts/run_full_verification.py
```

To run individual utilities:

### A. OCR Structural Comparison
Emits side-by-side metrics evaluating orphan tokens, row/column counts, and merged cell risks:
```bash
python3 verification/scripts/compare_ocr_results.py
```

### B. High-Visibility Layout Debug Rendering
Uses OpenCV to generate annotated bounding boxes, color-coding cells, table boundaries, and drawing **Orphan Tokens in bright magenta**:
```bash
python3 verification/scripts/render_layout_debug.py
```

### C. Financial Validation Reconciliation
Extracts prices, subtotals, and taxes to reconcile them via double-entry invoice accounting, highlighting geometry-reconstruction anomalies:
```bash
python3 verification/scripts/validate_invoice_math.py
```

---

## 3. Gitignore Protections
All subdirectories holding generated images (`*.jpg`, `*.png`), tables, reports, and comparisons are strictly ignored by `.gitignore` to keep git history lightweight and clean.
