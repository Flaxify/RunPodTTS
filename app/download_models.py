from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> None:
    model_dir = Path(os.getenv("INDEXTTS_MODEL_DIR", "/workspace/indextts/checkpoints"))
    model_repo = os.getenv("INDEXTTS_MODEL_REPO", "IndexTeam/IndexTTS-2")
    revision = os.getenv(
        "INDEXTTS_MODEL_REVISION",
        "740dcaff396282ffb241903d150ac011cd4b1ede",
    )
    config_path = model_dir / "config.yaml"
    completion_marker = model_dir / ".download-complete"

    if config_path.is_file() and completion_marker.is_file():
        print(f"IndexTTS checkpoints already present at {model_dir}", flush=True)
        return

    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {model_repo} to {model_dir}; first boot can take several minutes", flush=True)
    snapshot_download(repo_id=model_repo, revision=revision, local_dir=model_dir)

    if not config_path.is_file():
        raise RuntimeError(f"Model download completed but {config_path} is missing")
    completion_marker.write_text(f"{model_repo}@{revision}\n", encoding="utf-8")
    print("IndexTTS checkpoint download complete", flush=True)


if __name__ == "__main__":
    main()
