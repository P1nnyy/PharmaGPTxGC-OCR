# Wrong Column Assignment Audit

- Generated at: `2026-05-22T01:43:15`
- Forensic audit inputs: `0` from `forensic_runs`
- Benchmark JSON inputs: `0` from `scripts/benchmarks/outputs`
- Total wrong-column failures: **0**

## Summary

| Metric | Value |
| :--- | :--- |
| Total wrong-column failures | 0 |

## Failures By Invoice

| Invoice | Failures |
| :--- | :--- |
| none | 0 |

## Failures By Selected Topology

| Selected topology | Failures |
| :--- | :--- |
| none | 0 |

## Failures By Confusion Pattern

| Confusion pattern | Failures |
| :--- | :--- |
| none | 0 |

## Top Repeated Text Patterns

| Cell text | Occurrences |
| :--- | :--- |
| none | 0 |

## Pattern Examples

No failures with `Assigned Cause = cell assignment to wrong column` were found in the current local artifacts.

This usually means the benchmark outputs or `forensic_runs/*/row_math_failure_audit.md` files are absent from this checkout.

## Notes

- This report is diagnostic-only.
- No extraction, topology selection, row validation, or reconciliation code is modified by the audit generator.
- Confusion patterns are assigned by deterministic cell-text rules in `scratch/parse_wrong_columns.py`.
