# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.15 AS uv

FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ARG INDEXTTS_COMMIT=13495845e3028f0bb6ca1462ad22aa0e76349e40
ARG INDEXTTS_MODEL_REVISION=740dcaff396282ffb241903d150ac011cd4b1ede
ARG DEBIAN_FRONTEND=noninteractive

ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/indextts \
    PATH=/opt/indextts/.venv/bin:/opt/uv-python/bin:$PATH \
    INDEXTTS_MODEL_DIR=/opt/indextts/checkpoints \
    INDEXTTS_FP16=true \
    HF_HOME=/opt/huggingface \
    TORCH_HOME=/opt/torch

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
RUN git clone --filter=blob:none --no-checkout https://github.com/index-tts/index-tts.git /opt/indextts \
    && cd /opt/indextts \
    && git checkout "${INDEXTTS_COMMIT}" \
    && git lfs pull \
    && uv sync --frozen --no-dev --no-cache \
    && uv pip install --python /opt/indextts/.venv/bin/python --no-cache "runpod==1.11.0"

RUN /opt/indextts/.venv/bin/python -c \
    "from huggingface_hub import snapshot_download; snapshot_download(repo_id='IndexTeam/IndexTTS-2', revision='${INDEXTTS_MODEL_REVISION}', local_dir='/opt/indextts/checkpoints')"

RUN /opt/indextts/.venv/bin/python -c \
    "from indextts.utils.model_download import ensure_models_available; ensure_models_available('/opt/indextts/checkpoints')"

WORKDIR /app
COPY handler.py /app/handler.py

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/opt/indextts/.venv/bin/python", "-u", "/app/handler.py"]
