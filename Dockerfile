# The default extraction engine is Azure Document Intelligence
# (extraction/router.py), and requirements.txt - what this image actually
# installs - carries no torch/GPU dependency at all. Those live only in
# requirements-local.txt, for developers running the legacy Surya/PaddleOCR
# engine on their own machine. A production image that only ever runs the
# Azure engine has no use for a GPU, so this does not build on one: the
# previous version of this file based on a multi-gigabyte CUDA/cuDNN image to
# install a CPU-only package set, which cost real minutes and real money on
# every deploy for a capability nothing in the running container used.
#
# Multi-stage so the final image carries the installed packages but not the
# compilers and headers used to build them.

FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# gcc/build-essential cover the sdists that don't ship a manylinux wheel for
# every platform this might build on; removed after this stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/home/app/.local/bin:$PATH

WORKDIR /app

# libgl1/libglib2 satisfy Pillow's runtime image codecs; opencv is not part
# of the production dependency set so its heavier system libraries are not
# needed here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app \
    # WORKDIR creates /app as root before this point, and COPY --chown below
    # only chowns the files it places - not the directory it places them
    # into. Left as-is, the app user can copy-read its own code but cannot
    # create anything new under /app, which is exactly what the cache
    # directory needs to do on first request. Chowning the directory itself
    # here, before it has any contents, covers every subdirectory the app
    # creates later - datasets/ocr_results included - not just this one.
    && chown app:app /app

COPY --from=builder --chown=app:app /root/.local /home/app/.local

COPY --chown=app:app . .

USER app

EXPOSE 8000

# Read by the compose healthcheck and by any orchestrator that speaks the
# Docker HEALTHCHECK protocol, so a container that starts but can't serve
# traffic (e.g. Neo4j unreachable at boot) is visibly unhealthy rather than
# silently accepting connections it can't complete.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
