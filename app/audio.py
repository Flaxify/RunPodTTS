from __future__ import annotations

import subprocess


MEDIA_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "flac": "audio/flac",
}


def encode_audio(wav_bytes: bytes, output_format: str) -> bytes:
    if output_format == "wav":
        return wav_bytes

    output_args = {
        "mp3": ["-f", "mp3", "-codec:a", "libmp3lame", "-q:a", "2"],
        "opus": ["-f", "ogg", "-codec:a", "libopus", "-b:a", "96k"],
        "flac": ["-f", "flac"],
    }.get(output_format)
    if output_args is None:
        raise ValueError(f"Unsupported audio format: {output_format}")

    process = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            *output_args,
            "pipe:1",
        ],
        input=wav_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg audio conversion failed: {detail}")
    return process.stdout
