# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.15 AS uv

FROM nvidia/cuda:12.8.1-runtime-ubuntu22.04

ARG INDEXTTS_COMMIT=13495845e3028f0bb6ca1462ad22aa0e76349e40
ARG DEBIAN_FRONTEND=noninteractive

ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/indextts:/app \
    PATH=/opt/indextts/.venv/bin:/opt/uv-python/bin:$PATH \
    INDEXTTS_MODEL_DIR=/workspace/indextts/checkpoints \
    INDEXTTS_MODEL_REVISION=740dcaff396282ffb241903d150ac011cd4b1ede \
    INDEXTTS_VOICES_DIR=/workspace/indextts/voices \
    INDEXTTS_DEFAULT_VOICE=/workspace/indextts/voices/default.wav \
    INDEXTTS_API_KEY=sk-1234notsecure \
    INDEXTTS_REQUIRE_CUDA=true \
    INDEXTTS_FP16=true \
    HF_HOME=/workspace/huggingface

COPY --from=uv /uv /uvx /usr/local/bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        curl \
        ffmpeg \
        git \
        git-lfs \
        libgl1 \
        libglib2.0-0 \
        libsndfile1 \
        ninja-build \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install --system

WORKDIR /opt
RUN git clone --filter=blob:none https://github.com/index-tts/index-tts.git /opt/indextts \
    && cd /opt/indextts \
    && git checkout "${INDEXTTS_COMMIT}" \
    && git lfs pull \
    && uv sync --frozen --no-dev --no-cache

WORKDIR /app
COPY requirements-api.txt /tmp/requirements-api.txt
RUN uv pip install --python /opt/indextts/.venv/bin/python --no-cache -r /tmp/requirements-api.txt

COPY app /app/app
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
VOLUME ["/workspace"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/healthz >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
