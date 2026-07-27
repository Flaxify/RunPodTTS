from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    model_dir: Path
    voices_dir: Path
    default_voice_path: Path
    require_cuda: bool = True
    use_fp16: bool = True
    use_cuda_kernel: bool = False
    use_deepspeed: bool = False
    use_accel: bool = False
    use_torch_compile: bool = False
    max_text_chars: int = 4_000
    max_voice_bytes: int = 25 * 1024 * 1024
    host: str = "0.0.0.0"
    port: int = 8000
    public_base_url: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        pod_id = os.getenv("RUNPOD_POD_ID", "").strip()
        public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip() or None
        if public_base_url is None and pod_id:
            public_base_url = f"https://{pod_id}-8000.proxy.runpod.net"

        return cls(
            api_key=os.getenv("INDEXTTS_API_KEY", "sk-1234notsecure"),
            model_dir=Path(os.getenv("INDEXTTS_MODEL_DIR", "/workspace/indextts/checkpoints")),
            voices_dir=Path(os.getenv("INDEXTTS_VOICES_DIR", "/workspace/indextts/voices")),
            default_voice_path=Path(
                os.getenv(
                    "INDEXTTS_DEFAULT_VOICE",
                    "/workspace/indextts/voices/default.wav",
                )
            ),
            require_cuda=_env_bool("INDEXTTS_REQUIRE_CUDA", True),
            use_fp16=_env_bool("INDEXTTS_FP16", True),
            use_cuda_kernel=_env_bool("INDEXTTS_CUDA_KERNEL", False),
            use_deepspeed=_env_bool("INDEXTTS_DEEPSPEED", False),
            use_accel=_env_bool("INDEXTTS_ACCEL", False),
            use_torch_compile=_env_bool("INDEXTTS_TORCH_COMPILE", False),
            max_text_chars=int(os.getenv("INDEXTTS_MAX_TEXT_CHARS", "4000")),
            max_voice_bytes=int(os.getenv("INDEXTTS_MAX_VOICE_BYTES", str(25 * 1024 * 1024))),
            host=os.getenv("INDEXTTS_HOST", "0.0.0.0"),
            port=int(os.getenv("INDEXTTS_PORT", "8000")),
            public_base_url=public_base_url,
        )
