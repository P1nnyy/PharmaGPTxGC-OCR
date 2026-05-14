# PharmaGPT OCR API

A lightweight, GPU-first FastAPI application tailored for rapid experimentation with Surya OCR.
Optimized for an ML engineering workflow: Mac -> SSH -> Cloud GPU VM.

## Quick Start (Cloud GPU VM)

```bash
# Build and run the single-container Docker app
docker-compose up --build

# Or to run detached:
docker-compose up -d --build
```

## Testing the API

### 1. Health Check & GPU Verification
```bash
curl http://localhost:8000/health
```
**Expected Response:**
```json
{
  "status": "ok",
  "gpu_available": true,
  "gpu_name": "Tesla T4",
  "cuda_version": "12.8"
}
```

### 2. Upload Image for OCR
```bash
# Upload a sample invoice image
curl -X POST http://localhost:8000/upload-invoice \
  -H "Content-Type: multipart/form-data" \
  -F "file=@sample_invoice.jpg"
```

## Workflows
- **Caching**: The app hashes uploaded images (MD5) and saves OCR JSON outputs to `datasets/ocr_results/`. Subsequent uploads of the same image instantly return the JSON from cache.
- **Images**: Uploaded images are kept entirely in-memory and not written to disk to maximize IO speed during iteration.
- **Lazy Loading**: Surya OCR models are loaded into GPU memory precisely upon the first `POST /upload-invoice` request to minimize container startup delays.

## Table Reconstruction Defaults

Dense, borderless Indian pharma invoices currently default to `heuristic_anchor` topology because PPStructure frequently returns `tables=0, cells=0` on this layout class. PPStructure code remains available behind config: set `ENABLE_PPSTRUCTURE=true` or `TSR_PRIMARY_ENGINE=ppstructure` to re-enable the confidence-gated PPStructure path. Multi-orientation PPStructure probing is off by default; enable it with `ENABLE_PPSTRUCTURE_MULTI_ORIENTATION=true` only when explicitly debugging TSR orientation.

## Cache Directory Permissions

If benchmark runs log cache permission warnings, fix the local datasets ownership/permissions:

```bash
sudo chown -R $USER:$USER datasets
chmod -R u+rwX datasets
mkdir -p datasets/ocr_results
```
