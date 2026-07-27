from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings


class EngineNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class SynthesisOptions:
    text: str
    voice_path: Path
    emotion_audio_path: Path | None = None
    emotion_alpha: float = 1.0
    emotion_vector: list[float] | None = None
    use_emotion_text: bool = False
    emotion_text: str | None = None
    use_random: bool = False
    interval_silence_ms: int = 200
    top_p: float = 0.8
    top_k: int = 30
    temperature: float = 0.8
    repetition_penalty: float = 10.0
    max_mel_tokens: int = 1500


class TTSEngine(Protocol):
    @property
    def state(self) -> str: ...

    @property
    def error(self) -> str | None: ...

    def load(self) -> None: ...

    def synthesize(self, options: SynthesisOptions) -> bytes: ...


class IndexTTSEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self._state = "starting"
        self._error: str | None = None
        self._state_lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    @property
    def error(self) -> str | None:
        with self._state_lock:
            return self._error

    def _set_state(self, state: str, error: str | None = None) -> None:
        with self._state_lock:
            self._state = state
            self._error = error

    def load(self) -> None:
        with self._load_lock:
            if self.state == "ready":
                return

            self._set_state("loading")
            try:
                import torch
                from indextts.infer_v2 import IndexTTS2

                if self.settings.require_cuda and not torch.cuda.is_available():
                    raise RuntimeError("CUDA is required but torch.cuda.is_available() is false")

                config_path = self.settings.model_dir / "config.yaml"
                if not config_path.is_file():
                    raise FileNotFoundError(f"IndexTTS config not found: {config_path}")

                self._model = IndexTTS2(
                    cfg_path=str(config_path),
                    model_dir=str(self.settings.model_dir),
                    use_fp16=self.settings.use_fp16,
                    use_cuda_kernel=self.settings.use_cuda_kernel,
                    use_deepspeed=self.settings.use_deepspeed,
                    use_accel=self.settings.use_accel,
                    use_torch_compile=self.settings.use_torch_compile,
                )
                self._set_state("ready")
            except Exception as exc:
                self._set_state("error", f"{type(exc).__name__}: {exc}")
                raise

    def synthesize(self, options: SynthesisOptions) -> bytes:
        if self.state != "ready" or self._model is None:
            raise EngineNotReady(self.error or f"Model state is {self.state}")

        output_fd, output_name = tempfile.mkstemp(prefix="indextts-", suffix=".wav")
        os.close(output_fd)
        output_path = Path(output_name)

        try:
            with self._inference_lock:
                result = self._model.infer(
                    spk_audio_prompt=str(options.voice_path),
                    text=options.text,
                    output_path=str(output_path),
                    emo_audio_prompt=(
                        str(options.emotion_audio_path) if options.emotion_audio_path else None
                    ),
                    emo_alpha=options.emotion_alpha,
                    emo_vector=options.emotion_vector,
                    use_emo_text=options.use_emotion_text,
                    emo_text=options.emotion_text,
                    use_random=options.use_random,
                    interval_silence=options.interval_silence_ms,
                    verbose=False,
                    top_p=options.top_p,
                    top_k=options.top_k,
                    temperature=options.temperature,
                    repetition_penalty=options.repetition_penalty,
                    max_mel_tokens=options.max_mel_tokens,
                )

            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError(f"IndexTTS did not produce audio (result={result!r})")
            return output_path.read_bytes()
        finally:
            output_path.unlink(missing_ok=True)
