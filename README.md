# PharmaGPT

Extracts pharma distributor invoices into structured, reconcilable data:
line items, batches, expiry, tax, and a product catalogue that resolves the
same medicine across differently-worded invoices.

Extraction runs on **Azure Document Intelligence** (the default engine), with
Neo4j Aura for storage and Cloudflare R2 for scanned images — all managed
services, so the app itself is CPU-only and does not need a GPU.

A legacy Surya/PaddleOCR engine still exists behind `EXTRACTION_ENGINE=legacy`
for local experimentation. Its dependencies live in `requirements-local.txt`
and are deliberately kept out of `requirements.txt` and the production image.

**Deploying to a domain?** See [DEPLOY.md](DEPLOY.md).

## Quick Start (local)

```bash
# Build and run the API container
docker compose up --build

# Or to run detached:
docker-compose up -d --build
```

## Testing the API

### 1. Health Check
```bash
curl http://localhost:8000/health
```
**Expected Response** (the `gpu_*` fields report whether CUDA happens to be
available; they are `false`/`null` on the production image and on any machine
without a GPU, which is expected and not an error):
```json
{
  "status": "ok",
  "gpu_available": false,
  "gpu_name": null,
  "cuda_version": null
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
- **Lazy Loading**: When running the legacy engine, Surya OCR models load on the first `POST /upload-invoice` request rather than at startup. The default Azure engine loads nothing locally.

## Table Reconstruction Defaults

Dense, borderless Indian pharma invoices currently default to `heuristic_anchor` topology because PPStructure frequently returns `tables=0, cells=0` on this layout class. PPStructure code remains available behind config: set `ENABLE_PPSTRUCTURE=true` or `TSR_PRIMARY_ENGINE=ppstructure` to re-enable the confidence-gated PPStructure path. Multi-orientation PPStructure probing is off by default; enable it with `ENABLE_PPSTRUCTURE_MULTI_ORIENTATION=true` only when explicitly debugging TSR orientation.

## Cache Directory Permissions

If benchmark runs log cache permission warnings, fix the local datasets ownership/permissions:

```bash
sudo chown -R $USER:$USER datasets
chmod -R u+rwX datasets
mkdir -p datasets/ocr_results
```
