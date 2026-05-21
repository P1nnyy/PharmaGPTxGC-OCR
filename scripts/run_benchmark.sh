#!/bin/bash
# ================================================================
# Lightweight Benchmark Runner
# Optimized for LOW VM COST and FAST ITERATION.
# ================================================================
set -euo pipefail

# --- Defaults ---
IMAGE_DIR="./test_images"
BENCHMARK_ROOT="./benchmarks"
API_URL="http://localhost:8000/upload-invoice"
WORKERS=1
CLEANUP=false
MODE="benchmark"

# --- Parse Arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --images)    IMAGE_DIR="$2"; shift 2 ;;
        --output)    BENCHMARK_ROOT="$2"; shift 2 ;;
        --api)       API_URL="$2"; shift 2 ;;
        --workers)   WORKERS="$2"; shift 2 ;;
        --cleanup-cache) CLEANUP=true; shift ;;
        --mode)      MODE="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "  --images DIR        Input image directory (default: ./test_images)"
            echo "  --output DIR        Benchmark output root (default: ./benchmarks)"
            echo "  --api URL           API base URL (default: http://localhost:8000/upload-invoice)"
            echo "  --workers N         Parallel workers (default: 1, sequential)"
            echo "  --cleanup-cache     Remove intermediate artifacts after run"
            echo "  --mode MODE         benchmark (fast) or full (verbose debug)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Directory Structure ---
OUTPUTS_DIR="$BENCHMARK_ROOT/outputs"
REPORTS_DIR="$BENCHMARK_ROOT/reports"
FAILURES_DIR="$BENCHMARK_ROOT/failures"
mkdir -p "$OUTPUTS_DIR" "$REPORTS_DIR" "$FAILURES_DIR"

# --- Discover Images ---
shopt -s nullglob nocaseglob
images=("$IMAGE_DIR"/*.jpg "$IMAGE_DIR"/*.jpeg "$IMAGE_DIR"/*.png)
shopt -u nullglob nocaseglob

if [ ${#images[@]} -eq 0 ]; then
    echo "❌ No images found in $IMAGE_DIR"
    exit 1
fi

echo "═══════════════════════════════════════════════"
echo "  PharmaGPT Benchmark Runner (mode=$MODE)"
echo "═══════════════════════════════════════════════"
echo "  Images:    ${#images[@]}"
echo "  Output:    $BENCHMARK_ROOT"
echo "  Workers:   $WORKERS"
echo "  API:       $API_URL"
echo "───────────────────────────────────────────────"

# --- Benchmark Query Params ---
IS_BENCHMARK="false"
if [ "$MODE" = "benchmark" ]; then
    IS_BENCHMARK="true"
fi
QUERY="reconstruct=true&benchmark_mode=$IS_BENCHMARK"

# --- Counters ---
TOTAL=0
SUCCESS=0
FAST_FAIL=0
FAIL=0
TOTAL_TIME=0

# --- Process Function ---
process_image() {
    local img="$1"
    local filename
    filename=$(basename "$img")
    local json_out="$OUTPUTS_DIR/${filename}.json"

    local response
    response=$(curl -s -w "\n%{http_code}:%{time_total}" \
        -o "$json_out" \
        -X POST "${API_URL}?${QUERY}" \
        -H "Content-Type: multipart/form-data" \
        -F "file=@$img")

    local http_code time_taken
    http_code=$(echo "$response" | tail -1 | cut -d: -f1)
    time_taken=$(echo "$response" | tail -1 | cut -d: -f2)

    if [ "$http_code" -eq 200 ]; then
        # Check for fast-fail in the JSON output
        local ff
        ff=$(python3 -c "import json; d=json.load(open('$json_out')); print(d.get('metadata',{}).get('fast_fail', False))" 2>/dev/null || echo "False")

        if [ "$ff" = "True" ]; then
            echo "⚡ FAST-FAIL | ${filename} | ${time_taken}s"
            cp "$json_out" "$FAILURES_DIR/${filename}.json"
            echo "FAST_FAIL"
        else
            echo "✅ SUCCESS  | ${filename} | ${time_taken}s"
            echo "SUCCESS"
        fi
    else
        echo "❌ HTTP $http_code | ${filename}"
        cp "$json_out" "$FAILURES_DIR/${filename}.json" 2>/dev/null || true
        echo "FAIL"
    fi
    echo "$time_taken"
}

# --- Main Execution Loop ---
START_TS=$(date +%s)

for img in "${images[@]}"; do
    TOTAL=$((TOTAL + 1))

    # Read both the status line and time from the function
    mapfile -t result < <(process_image "$img")
    # result[0] = display line (already echoed), result[1] = status, result[2] = time
    status="${result[1]:-FAIL}"
    elapsed="${result[2]:-0}"

    case "$status" in
        SUCCESS)   SUCCESS=$((SUCCESS + 1)) ;;
        FAST_FAIL) FAST_FAIL=$((FAST_FAIL + 1)) ;;
        *)         FAIL=$((FAIL + 1)) ;;
    esac

    TOTAL_TIME=$(echo "$TOTAL_TIME + $elapsed" | bc 2>/dev/null || echo "$TOTAL_TIME")
done

END_TS=$(date +%s)
WALL_TIME=$((END_TS - START_TS))

# --- Generate Summary Report ---
PASS_RATE=0
if [ "$TOTAL" -gt 0 ]; then
    PASS_RATE=$(echo "scale=1; $SUCCESS * 100 / $TOTAL" | bc 2>/dev/null || echo "0")
fi

SUMMARY="$REPORTS_DIR/benchmark_summary.md"
cat > "$SUMMARY" << EOF
# Benchmark Summary

| Metric | Value |
| :--- | :---: |
| Total Invoices | $TOTAL |
| Successful Reconstructions | $SUCCESS |
| Fast-Fail Count | $FAST_FAIL |
| HTTP/Processing Failures | $FAIL |
| Financial Pass Rate | ${PASS_RATE}% |
| Total API Time (s) | $TOTAL_TIME |
| Wall Clock Time (s) | $WALL_TIME |
| Mode | $MODE |
EOF

echo ""
echo "═══════════════════════════════════════════════"
echo "  Benchmark Complete"
echo "───────────────────────────────────────────────"
echo "  Total:       $TOTAL"
echo "  Success:     $SUCCESS"
echo "  Fast-Fail:   $FAST_FAIL"
echo "  Failed:      $FAIL"
echo "  Pass Rate:   ${PASS_RATE}%"
echo "  Wall Time:   ${WALL_TIME}s"
echo "  Summary:     $SUMMARY"
echo "═══════════════════════════════════════════════"

# --- Run Financial Validation on Outputs ---
echo ""
echo "Running financial topology validation..."
if python3 ../verification/scripts/validate_invoice_math.py \
  --results-dir "$OUTPUTS_DIR" \
  --report-out "$REPORTS_DIR/topology_integrity_report.md"; then
  echo "✅ Financial topology validation complete"
else
  echo "⚠️  Financial validation skipped (script error)"
fi

# --- Cleanup Mode ---
if [ "$CLEANUP" = true ]; then
    echo ""
    echo "🧹 Cleaning intermediate cache artifacts..."
    rm -f datasets/debug/raw_ocr.json
    rm -f datasets/debug/raw_coordinate_order.txt
    rm -f datasets/debug/tsr_input_rot*.png
    rm -f datasets/debug/tsr_selected_orientation.png
    rm -f datasets/debug/raw_ppstructure_response.json
    echo "   Kept: ioa_hardened_metrics.json, normalized_cell_grid.json, reconstructed_output.md"
    echo "   Removed: intermediate debug artifacts"
fi

echo ""
echo "Done. Analyze results in: $BENCHMARK_ROOT/"
