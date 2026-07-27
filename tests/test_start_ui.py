from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

import pytest


ROOT = pathlib.Path(__file__).parents[1]
START_SCRIPT = ROOT / "start.sh"

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="start.sh behavior tests run under Bash on POSIX CI; WSL is validated separately",
)


def run_bash(script: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", "-c", script, "bash", str(START_SCRIPT)],
        cwd=ROOT,
        env=merged_env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_start_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(START_SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_demo_gpu_offers_are_sorted_by_price() -> None:
    result = run_bash(
        'RUNPODTTS_SOURCE_ONLY=1 source "$1"; '
        "sorted_offer_records SECURE; sorted_offer_records COMMUNITY"
    )

    assert result.returncode == 0, result.stderr
    prices = [float(line.split("|", 1)[0]) for line in result.stdout.splitlines()]
    assert prices[:3] == sorted(prices[:3])
    assert prices[3:] == sorted(prices[3:])


def test_demo_state_round_trip(tmp_path: pathlib.Path) -> None:
    state_file = tmp_path / "state"
    result = run_bash(
        'RUNPODTTS_SOURCE_ONLY=1 source "$1"; '
        'POD_ID="demo-pod"; POD_NAME="RunPodTTS"; POD_SOURCE="SECURE CLOUD"; '
        'POD_GPU="NVIDIA RTX A5000"; POD_VRAM="24 GB"; POD_STATUS="RUNNING"; '
        'POD_RATE="0.27"; POD_INDEX_KEY="sk-demo"; '
        'POD_URL="https://demo-pod-8000.proxy.runpod.net"; '
        'POD_STORAGE="50 GB persistent Pod volume"; save_state; '
        'reset_state_variables; load_state; '
        "printf '%s|%s|%s|%s' \"$POD_ID\" \"$POD_STATUS\" \"$POD_INDEX_KEY\" \"$POD_URL\"",
        env={"RUNPODTTS_STATE_FILE": str(state_file)},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "demo-pod|RUNNING|sk-demo|https://demo-pod-8000.proxy.runpod.net"
    )
    assert state_file.stat().st_mode & 0o777 == 0o600


def test_complete_demo_setup_flow(tmp_path: pathlib.Path) -> None:
    fake_gum = tmp_path / "gum"
    state_file = tmp_path / "state"
    shutil.copy2(ROOT / "tests" / "fake_gum.sh", fake_gum)
    fake_gum.chmod(0o755)

    result = subprocess.run(
        ["bash", str(START_SCRIPT)],
        cwd=ROOT,
        env={
            **os.environ,
            "RUNPODTTS_GUM": str(fake_gum),
            "RUNPODTTS_STATE_FILE": str(state_file),
            "RUNPODTTS_NO_CLEAR": "1",
            "RUNPOD_API_KEY": "demo-runpod-key",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    state_fields = state_file.read_text().rstrip("\n").split("\t")
    assert state_fields[3] == "SECURE CLOUD"
    assert state_fields[4] == "NVIDIA RTX A5000"
    assert state_fields[6] == "RUNNING"
    assert state_fields[7] == "0.27"
    assert state_fields[8] == "sk-demo-ui"
    assert state_fields[9].endswith("-8000.proxy.runpod.net")
    assert "SETUP COMPLETE (DEMO)" in result.stdout
