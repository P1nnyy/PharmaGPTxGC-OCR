#!/bin/bash
# ---------------------------------------------------------
# Run this on your Cloud GPU VM inside ~/PharmaGPTxGC-OCR
# ---------------------------------------------------------

IMAGE_DIR="./test_images"
RESULTS_DIR="./results"
API_URL="http://localhost:8000/upload-invoice?reconstruct=true"

# Ensure results directory exists
mkdir -p "$RESULTS_DIR"

echo "========================================="
echo " Starting OCR Benchmark"
echo "========================================="

# Enable case-insensitive and null globbing
shopt -s nullglob nocaseglob
images=("$IMAGE_DIR"/*.jpg "$IMAGE_DIR"/*.jpeg "$IMAGE_DIR"/*.png)

if [ ${#images[@]} -eq 0 ]; then
    echo "❌ No images found in $IMAGE_DIR. Did you run upload_invoices.sh on your Mac?"
    exit 1
fi

echo "Target Endpoint: $API_URL"
echo "Total Images: ${#images[@]}"
echo "Results Dir: $RESULTS_DIR"
echo "-----------------------------------------"

for img in "${images[@]}"; do
    filename=$(basename "$img")
    json_out="$RESULTS_DIR/${filename}.json"
    
    echo -n "Processing: $filename ... "
    
    # Run curl, capture output into json_out, and print HTTP code + total time
    # We use -w to format the output string we capture into the 'response' variable
    response=$(curl -s -w "%{http_code}:%{time_total}\n" \
               -o "$json_out" \
               -X POST "$API_URL" \
               -H "Content-Type: multipart/form-data" \
               -F "file=@$img")
               
    # Extract comma-separated stats
    http_code=$(echo "$response" | cut -d: -f1)
    time_taken=$(echo "$response" | cut -d: -f2)
    
    if [ "$http_code" -eq 200 ]; then
        echo "✅ Success | Time: ${time_taken}s | Saved: $json_out"
    else
        echo "❌ Failed  | HTTP: $http_code | See $json_out for details"
    fi
done

echo "========================================="
echo "Benchmark Complete! All results saved to $RESULTS_DIR"
