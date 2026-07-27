from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.audio import MEDIA_TYPES, encode_audio
from app.auth import make_api_key_dependency
from app.config import Settings
from app.engine import EngineNotReady, IndexTTSEngine, SynthesisOptions, TTSEngine
from app.voices import VoiceStore


logger = logging.getLogger("indextts-cloud")


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = "indextts-2"
    input: str = Field(min_length=1)
    voice: str = "default"
    response_format: Literal["wav", "mp3", "opus", "flac"] = "wav"
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    emotion_alpha: float = Field(default=1.0, ge=0.0, le=1.0)
    emotion_vector: list[float] | None = None
    use_emotion_text: bool = False
    emotion_text: str | None = None
    use_random: bool = False
    interval_silence_ms: int = Field(default=200, ge=0, le=2_000)
    top_p: float = Field(default=0.8, gt=0.0, le=1.0)
    top_k: int = Field(default=30, ge=1, le=200)
    temperature: float = Field(default=0.8, gt=0.0, le=2.0)
    repetition_penalty: float = Field(default=10.0, ge=0.1, le=30.0)
    max_mel_tokens: int = Field(default=1_500, ge=64, le=4_000)

    @field_validator("emotion_vector")
    @classmethod
    def validate_emotion_vector(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        if len(value) != 8:
            raise ValueError("emotion_vector must contain exactly 8 values")
        if any(item < 0.0 or item > 1.0 for item in value):
            raise ValueError("emotion_vector values must be between 0 and 1")
        return value


class VoiceResponse(BaseModel):
    voice_id: str
    filename: str
    size: int


def create_app(
    settings: Settings | None = None,
    engine: TTSEngine | None = None,
    *,
    load_engine: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = engine or IndexTTSEngine(settings)
    voices = VoiceStore(settings.voices_dir, settings.default_voice_path)
    require_api_key = make_api_key_dependency(settings.api_key)

    def report_load_result(task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("IndexTTS model failed to load")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        load_task: asyncio.Task[None] | None = None
        if load_engine:
            load_task = asyncio.create_task(asyncio.to_thread(engine.load))
            load_task.add_done_callback(report_load_result)
        yield
        if load_task is not None and not load_task.done():
            load_task.cancel()

    app = FastAPI(
        title="IndexTTS Cloud",
        version="0.1.0",
        description="A small authenticated HTTP wrapper for IndexTTS2 on Runpod.",
        lifespan=lifespan,
    )

    @app.get("/")
    async def root() -> dict[str, str | None]:
        return {
            "service": "IndexTTS Cloud",
            "state": engine.state,
            "docs": "/docs",
            "endpoint": settings.public_base_url,
        }

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "model_state": engine.state}

    @app.get("/readyz")
    async def ready():
        if engine.state != "ready":
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "model_state": engine.state, "error": engine.error},
            )
        return {"status": "ready", "model_state": engine.state}

    @app.get("/v1/info", dependencies=[Depends(require_api_key)])
    async def info() -> dict[str, object]:
        return {
            "service": "IndexTTS Cloud",
            "model": "indextts-2",
            "model_state": engine.state,
            "endpoint": settings.public_base_url,
            "voices": voices.list(),
            "audio_formats": list(MEDIA_TYPES),
        }

    @app.get("/v1/models", dependencies=[Depends(require_api_key)])
    async def models() -> dict[str, object]:
        return {
            "object": "list",
            "data": [{"id": "indextts-2", "object": "model", "owned_by": "IndexTeam"}],
        }

    @app.get("/v1/voices", dependencies=[Depends(require_api_key)])
    async def list_voices() -> dict[str, list[str]]:
        return {"voices": voices.list()}

    @app.post(
        "/v1/voices",
        response_model=VoiceResponse,
        dependencies=[Depends(require_api_key)],
    )
    async def upload_voice(
        voice_id: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
    ) -> VoiceResponse:
        content = await file.read(settings.max_voice_bytes + 1)
        if not content:
            raise HTTPException(status_code=400, detail="Voice file is empty")
        if len(content) > settings.max_voice_bytes:
            raise HTTPException(status_code=413, detail="Voice file is too large")
        try:
            path = voices.save(voice_id, file.filename, content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return VoiceResponse(voice_id=voice_id, filename=path.name, size=len(content))

    async def synthesize(request: SpeechRequest) -> Response:
        if len(request.input) > settings.max_text_chars:
            raise HTTPException(
                status_code=413,
                detail=f"Text exceeds {settings.max_text_chars} characters",
            )
        if request.speed != 1.0:
            raise HTTPException(status_code=400, detail="IndexTTS speed control is not implemented")
        try:
            voice_path = voices.resolve(request.voice)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        options = SynthesisOptions(
            text=request.input,
            voice_path=voice_path,
            emotion_alpha=request.emotion_alpha,
            emotion_vector=request.emotion_vector,
            use_emotion_text=request.use_emotion_text,
            emotion_text=request.emotion_text,
            use_random=request.use_random,
            interval_silence_ms=request.interval_silence_ms,
            top_p=request.top_p,
            top_k=request.top_k,
            temperature=request.temperature,
            repetition_penalty=request.repetition_penalty,
            max_mel_tokens=request.max_mel_tokens,
        )

        started = time.perf_counter()
        try:
            audio = await asyncio.to_thread(engine.synthesize, options)
        except EngineNotReady as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        elapsed = time.perf_counter() - started

        encoded_audio = await asyncio.to_thread(encode_audio, audio, request.response_format)
        return Response(
            content=encoded_audio,
            media_type=MEDIA_TYPES[request.response_format],
            headers={
                "Content-Disposition": (
                    f'inline; filename="speech.{request.response_format}"'
                ),
                "X-Generation-Seconds": f"{elapsed:.3f}",
            },
        )

    app.post("/v1/audio/speech", dependencies=[Depends(require_api_key)])(synthesize)
    app.post("/tts", dependencies=[Depends(require_api_key)])(synthesize)

    return app


app = create_app()
