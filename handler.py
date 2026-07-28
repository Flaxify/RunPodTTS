from __future__ import annotations

import base64
import binascii
import os
import tempfile
from pathlib import Path
from typing import Any

import runpod
import torch
from indextts.infer_v2 import IndexTTS2


MODEL_DIR = Path(os.getenv("INDEXTTS_MODEL_DIR", "/opt/indextts/checkpoints"))
MAX_TEXT_LENGTH = int(os.getenv("INDEXTTS_MAX_TEXT_LENGTH", "1000"))
MAX_VOICE_BYTES = int(os.getenv("INDEXTTS_MAX_VOICE_BYTES", str(12 * 1024 * 1024)))
MAX_OUTPUT_BYTES = int(os.getenv("INDEXTTS_MAX_OUTPUT_BYTES", str(14 * 1024 * 1024)))


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_model() -> IndexTTS2:
    if not torch.cuda.is_available():
        raise RuntimeError("IndexTTS requires a CUDA GPU worker")

    config_path = MODEL_DIR / "config.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"IndexTTS config not found: {config_path}")

    return IndexTTS2(
        cfg_path=str(config_path),
        model_dir=str(MODEL_DIR),
        use_fp16=env_flag("INDEXTTS_FP16", True),
        use_cuda_kernel=env_flag("INDEXTTS_CUDA_KERNEL"),
        use_deepspeed=env_flag("INDEXTTS_DEEPSPEED"),
        use_accel=env_flag("INDEXTTS_ACCEL"),
        use_torch_compile=env_flag("INDEXTTS_TORCH_COMPILE"),
    )


MODEL = load_model()


def require_input(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("input")
    if not isinstance(payload, dict):
        raise ValueError("job.input must be an object")
    return payload


def decode_audio(payload: dict[str, Any], field: str) -> bytes:
    encoded = payload.get(field)
    if not isinstance(encoded, str) or not encoded:
        raise ValueError(f"input.{field} must be a non-empty base64 string")
    if encoded.startswith("data:"):
        try:
            encoded = encoded.split(",", 1)[1]
        except IndexError as exc:
            raise ValueError(f"input.{field} contains an invalid data URL") from exc

    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"input.{field} is not valid base64") from exc
    if not audio:
        raise ValueError(f"input.{field} decoded to an empty file")
    if len(audio) > MAX_VOICE_BYTES:
        raise ValueError(
            f"input.{field} exceeds the {MAX_VOICE_BYTES}-byte worker limit"
        )
    return audio


def handler(job: dict[str, Any]) -> dict[str, Any]:
    payload = require_input(job)
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("input.text must be a non-empty string")
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f"input.text exceeds {MAX_TEXT_LENGTH} characters")

    voice_audio = decode_audio(payload, "voice_base64")
    emotion_audio = (
        decode_audio(payload, "emotion_base64")
        if payload.get("emotion_base64")
        else None
    )
    combined_audio_bytes = len(voice_audio) + (
        len(emotion_audio) if emotion_audio is not None else 0
    )
    if combined_audio_bytes > MAX_VOICE_BYTES:
        raise ValueError(
            "combined voice and emotion audio exceed the queue payload safety limit"
        )

    with tempfile.TemporaryDirectory(prefix="indextts-") as temp_dir:
        temp_path = Path(temp_dir)
        voice_path = temp_path / "voice.wav"
        output_path = temp_path / "speech.wav"
        voice_path.write_bytes(voice_audio)

        emotion_path: Path | None = None
        if emotion_audio is not None:
            emotion_path = temp_path / "emotion.wav"
            emotion_path.write_bytes(emotion_audio)

        MODEL.infer(
            spk_audio_prompt=str(voice_path),
            text=text.strip(),
            output_path=str(output_path),
            emo_audio_prompt=str(emotion_path) if emotion_path else None,
            emo_alpha=float(payload.get("emotion_alpha", 1.0)),
            use_emo_text=bool(payload.get("use_emotion_text", False)),
            emo_text=payload.get("emotion_text"),
            use_random=bool(payload.get("use_random", False)),
            verbose=False,
        )

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError("IndexTTS did not produce a WAV file")
        output_audio = output_path.read_bytes()
        if len(output_audio) > MAX_OUTPUT_BYTES:
            raise RuntimeError("generated WAV exceeds the queue response safety limit")
        audio_base64 = base64.b64encode(output_audio).decode("ascii")

    return {
        "audio_base64": audio_base64,
        "audio_format": "wav",
    }


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
