from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.engine import SynthesisOptions
from app.main import create_app


WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt " + (b"\x00" * 24)


class FakeEngine:
    state = "ready"
    error = None
    last_options: SynthesisOptions | None = None

    def load(self) -> None:
        self.state = "ready"

    def synthesize(self, options: SynthesisOptions) -> bytes:
        self.last_options = options
        return WAV_BYTES


def make_client(tmp_path: Path) -> tuple[TestClient, FakeEngine]:
    default_voice = tmp_path / "default.wav"
    default_voice.write_bytes(WAV_BYTES)
    settings = Settings(
        api_key="sk-1234notsecure",
        model_dir=tmp_path / "models",
        voices_dir=tmp_path / "voices",
        default_voice_path=default_voice,
        require_cuda=False,
    )
    engine = FakeEngine()
    app = create_app(settings=settings, engine=engine, load_engine=False)
    return TestClient(app), engine


def test_health_is_public_and_speech_requires_key(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    with client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/v1/audio/speech", json={"input": "Hello"}).status_code == 401


def test_openai_style_speech_endpoint_returns_wav(tmp_path: Path) -> None:
    client, engine = make_client(tmp_path)
    with client:
        response = client.post(
            "/v1/audio/speech",
            headers={"Authorization": "Bearer sk-1234notsecure"},
            json={"model": "indextts-2", "input": "Hello from Runpod", "voice": "default"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == WAV_BYTES
    assert engine.last_options is not None
    assert engine.last_options.text == "Hello from Runpod"


def test_upload_and_use_voice(tmp_path: Path) -> None:
    client, engine = make_client(tmp_path)
    auth = {"X-API-Key": "sk-1234notsecure"}
    with client:
        upload = client.post(
            "/v1/voices",
            headers=auth,
            data={"voice_id": "hero"},
            files={"file": ("hero.wav", WAV_BYTES, "audio/wav")},
        )
        speech = client.post(
            "/tts",
            headers=auth,
            json={"input": "We ride at dawn", "voice": "hero"},
        )

    assert upload.status_code == 200
    assert upload.json()["voice_id"] == "hero"
    assert speech.status_code == 200
    assert engine.last_options is not None
    assert engine.last_options.voice_path.name == "hero.wav"
