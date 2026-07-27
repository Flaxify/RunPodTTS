#!/usr/bin/env bash
set -Eeuo pipefail

export INDEXTTS_MODEL_DIR="${INDEXTTS_MODEL_DIR:-/workspace/indextts/checkpoints}"
export INDEXTTS_VOICES_DIR="${INDEXTTS_VOICES_DIR:-/workspace/indextts/voices}"
export HF_HOME="${HF_HOME:-/workspace/huggingface}"

mkdir -p "${INDEXTTS_MODEL_DIR}" "${INDEXTTS_VOICES_DIR}" "${HF_HOME}"

python -m app.download_models

echo "Starting IndexTTS Cloud on 0.0.0.0:${INDEXTTS_PORT:-8000}"
if [[ -n "${RUNPOD_POD_ID:-}" ]]; then
  echo "INDEXTTS_ENDPOINT=https://${RUNPOD_POD_ID}-${INDEXTTS_PORT:-8000}.proxy.runpod.net"
fi

exec uvicorn app.main:app \
  --host "${INDEXTTS_HOST:-0.0.0.0}" \
  --port "${INDEXTTS_PORT:-8000}" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips="*"
