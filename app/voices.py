from __future__ import annotations

import re
from pathlib import Path


VOICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ALLOWED_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


class VoiceStore:
    def __init__(self, voices_dir: Path, default_voice_path: Path):
        self.voices_dir = voices_dir
        self.default_voice_path = default_voice_path

    @staticmethod
    def validate_voice_id(voice_id: str) -> str:
        if not VOICE_ID_PATTERN.fullmatch(voice_id):
            raise ValueError(
                "voice_id must be 1-64 characters using letters, numbers, dot, underscore, or dash"
            )
        return voice_id

    def list(self) -> list[str]:
        voice_ids: set[str] = set()
        if self.default_voice_path.is_file():
            voice_ids.add("default")
        if not self.voices_dir.is_dir():
            return sorted(voice_ids)
        for path in self.voices_dir.iterdir():
            if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES:
                voice_ids.add(path.stem)
        return sorted(voice_ids)

    def resolve(self, voice_id: str) -> Path:
        self.validate_voice_id(voice_id)
        if voice_id == "default":
            uploaded_defaults = (
                [
                    path
                    for path in self.voices_dir.glob("default.*")
                    if path.suffix.lower() in ALLOWED_SUFFIXES
                ]
                if self.voices_dir.is_dir()
                else []
            )
            path = uploaded_defaults[0] if uploaded_defaults else self.default_voice_path
        else:
            matches = [
                path
                for path in self.voices_dir.glob(f"{voice_id}.*")
                if path.suffix.lower() in ALLOWED_SUFFIXES
            ]
            path = matches[0] if matches else self.voices_dir / f"{voice_id}.wav"

        if not path.is_file():
            raise FileNotFoundError(f"Voice '{voice_id}' does not exist")
        return path

    def save(self, voice_id: str, filename: str | None, content: bytes) -> Path:
        self.validate_voice_id(voice_id)
        suffix = Path(filename or "voice.wav").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"Unsupported voice format: {suffix or '(none)'}")

        self.voices_dir.mkdir(parents=True, exist_ok=True)
        for existing in self.voices_dir.glob(f"{voice_id}.*"):
            if existing.is_file() and existing.suffix.lower() in ALLOWED_SUFFIXES:
                existing.unlink()

        destination = self.voices_dir / f"{voice_id}{suffix}"
        destination.write_bytes(content)
        return destination
