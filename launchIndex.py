#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_INDEXTTS_API_KEY = "sk-1234notsecure"
DEFAULT_GPU_TYPES = [
    "NVIDIA GeForce RTX 4090",
    "NVIDIA GeForce RTX 3090",
    "NVIDIA RTX A5000",
    "NVIDIA L4",
    "NVIDIA A40",
    "NVIDIA RTX A6000",
]
DEFAULT_PORT = 8000
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STATE_FILE = SCRIPT_DIR / ".runpod-index.json"


class LauncherError(RuntimeError):
    pass


@dataclass
class DeploymentState:
    pod_id: str
    endpoint: str
    index_api_key: str
    image: str
    created_at: str

    @classmethod
    def load(cls, path: Path) -> "DeploymentState":
        try:
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            raise LauncherError(f"Could not read deployment state from {path}: {exc}") from exc

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.__dict__, indent=2) + "\n", encoding="utf-8")


class RunpodClient:
    def __init__(self, api_key: str, base_url: str = "https://rest.runpod.io/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "IndexTTS-Cloud-Launcher/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content = response.read()
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LauncherError(f"Runpod API returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LauncherError(f"Could not reach Runpod API: {exc.reason}") from exc

    def create_pod(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.request("POST", "/pods", payload)
        if not isinstance(result, dict) or not result.get("id"):
            raise LauncherError(f"Runpod create response did not contain a pod id: {result!r}")
        return result

    def get_pod(self, pod_id: str) -> dict[str, Any]:
        result = self.request("GET", f"/pods/{pod_id}")
        if not isinstance(result, dict):
            raise LauncherError(f"Unexpected Runpod pod response: {result!r}")
        return result

    def action(self, pod_id: str, action: str) -> dict[str, Any]:
        result = self.request("POST", f"/pods/{pod_id}/{action}")
        return result if isinstance(result, dict) else {}

    def terminate(self, pod_id: str) -> None:
        self.request("DELETE", f"/pods/{pod_id}")


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise LauncherError(f"{name} is required; put it in .env or export it in WSL2")
    return value


def endpoint_for(pod_id: str, port: int = DEFAULT_PORT) -> str:
    return f"https://{pod_id}-{port}.proxy.runpod.net"


def print_connection(state: DeploymentState) -> None:
    print()
    print("IndexTTS connection details")
    print(f"INDEXTTS_URL={state.endpoint}")
    print(f"INDEXTTS_API_KEY={state.index_api_key}")
    print(f"RUNPOD_POD_ID={state.pod_id}")
    print()
    print("OpenAPI docs:")
    print(f"{state.endpoint}/docs")


def probe_ready(endpoint: str, index_api_key: str) -> tuple[bool, str]:
    request = urllib.request.Request(
        f"{endpoint}/readyz",
        headers={
            "Authorization": f"Bearer {index_api_key}",
            "User-Agent": "IndexTTS-Cloud-Launcher/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read())
            return response.status == 200 and payload.get("status") == "ready", str(payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
            if payload.get("model_state") == "error":
                raise LauncherError(f"IndexTTS model failed to load: {payload.get('error')}")
            return False, str(payload)
        except json.JSONDecodeError:
            return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return False, str(exc)


def wait_until_ready(state: DeploymentState, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    last_detail = "not contacted yet"
    print("Waiting for the image, model download, and GPU model load", end="", flush=True)
    while time.monotonic() < deadline:
        attempt += 1
        ready, last_detail = probe_ready(state.endpoint, state.index_api_key)
        if ready:
            print(" ready.")
            return
        print(".", end="", flush=True)
        time.sleep(min(10, 2 + attempt))
    print()
    raise LauncherError(
        f"Pod {state.pod_id} did not become ready within {timeout_seconds}s. "
        f"Last response: {last_detail}. It was left running for inspection."
    )


def build_create_payload(image: str, index_api_key: str, args: argparse.Namespace) -> dict[str, Any]:
    gpu_types = [item.strip() for item in args.gpu_types.split(",") if item.strip()]
    if not gpu_types:
        raise LauncherError("At least one GPU type must be configured")

    payload: dict[str, Any] = {
        "name": args.name
        or f"indextts-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "cloudType": args.cloud_type,
        "computeType": "GPU",
        "allowedCudaVersions": ["12.8", "12.9", "13.0"],
        "gpuCount": 1,
        "gpuTypeIds": gpu_types,
        "gpuTypePriority": "availability",
        "imageName": image,
        "containerDiskInGb": args.container_disk,
        "minRAMPerGPU": 16,
        "minVCPUPerGPU": 4,
        "volumeMountPath": "/workspace",
        "ports": [f"{DEFAULT_PORT}/http"],
        "supportPublicIp": True,
        "interruptible": args.spot,
        "env": {
            "INDEXTTS_API_KEY": index_api_key,
            "INDEXTTS_MODEL_DIR": "/workspace/indextts/checkpoints",
            "INDEXTTS_MODEL_REVISION": "740dcaff396282ffb241903d150ac011cd4b1ede",
            "INDEXTTS_VOICES_DIR": "/workspace/indextts/voices",
            "INDEXTTS_REQUIRE_CUDA": "true",
            "INDEXTTS_FP16": "true",
            "HF_HOME": "/workspace/huggingface",
        },
    }
    if args.network_volume:
        payload["networkVolumeId"] = args.network_volume
    else:
        payload["volumeInGb"] = args.volume_disk
    return payload


def command_launch(args: argparse.Namespace, client: RunpodClient, state_file: Path) -> int:
    if state_file.exists() and not args.force_new:
        existing = DeploymentState.load(state_file)
        raise LauncherError(
            f"A deployment is already recorded for pod {existing.pod_id}. "
            "Run status/terminate, delete the state file, or pass --force-new."
        )

    image = args.image or required_env("INDEXTTS_IMAGE")
    index_api_key = args.index_api_key
    payload = build_create_payload(image, index_api_key, args)

    print(f"Creating Runpod Pod from {image}...")
    pod = client.create_pod(payload)
    pod_id = str(pod["id"])
    state = DeploymentState(
        pod_id=pod_id,
        endpoint=endpoint_for(pod_id),
        index_api_key=index_api_key,
        image=image,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    state.save(state_file)
    print(f"Created pod {pod_id}; estimated hourly cost: {pod.get('costPerHr', 'unknown')}")
    print_connection(state)

    if not args.no_wait:
        wait_until_ready(state, args.timeout)
        print_connection(state)
    return 0


def command_status(_: argparse.Namespace, client: RunpodClient, state_file: Path) -> int:
    state = DeploymentState.load(state_file)
    pod = client.get_pod(state.pod_id)
    desired_status = str(pod.get("desiredStatus", "unknown"))
    if desired_status.upper() == "RUNNING":
        ready, detail = probe_ready(state.endpoint, state.index_api_key)
    else:
        ready, detail = False, f"pod desired status is {desired_status}"
    print(f"Pod: {state.pod_id}")
    print(f"Desired status: {desired_status}")
    print(f"Ready: {'yes' if ready else 'no'} ({detail})")
    print(f"Cost/hour: {pod.get('costPerHr', 'unknown')}")
    print_connection(state)
    return 0


def command_start(args: argparse.Namespace, client: RunpodClient, state_file: Path) -> int:
    state = DeploymentState.load(state_file)
    client.action(state.pod_id, "start")
    print(f"Start requested for pod {state.pod_id}")
    if not args.no_wait:
        wait_until_ready(state, args.timeout)
    print_connection(state)
    return 0


def command_stop(_: argparse.Namespace, client: RunpodClient, state_file: Path) -> int:
    state = DeploymentState.load(state_file)
    client.action(state.pod_id, "stop")
    print(f"Stop requested for pod {state.pod_id}. The /workspace volume is retained.")
    return 0


def command_terminate(args: argparse.Namespace, client: RunpodClient, state_file: Path) -> int:
    state = DeploymentState.load(state_file)
    if not args.yes:
        raise LauncherError(
            "Termination deletes the Pod and its attached volume. Re-run with: terminate --yes"
        )
    client.terminate(state.pod_id)
    state_file.unlink(missing_ok=True)
    print(f"Terminated pod {state.pod_id} and removed {state_file.name}")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch and manage IndexTTS on Runpod")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(os.getenv("INDEXTTS_STATE_FILE", DEFAULT_STATE_FILE)),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    launch = subparsers.add_parser("launch", help="Create a new IndexTTS Pod")
    launch.add_argument("--image", default=os.getenv("INDEXTTS_IMAGE"))
    launch.add_argument("--index-api-key", default=os.getenv("INDEXTTS_API_KEY", DEFAULT_INDEXTTS_API_KEY))
    launch.add_argument("--name")
    launch.add_argument(
        "--gpu-types",
        default=os.getenv("RUNPOD_GPU_TYPES", ",".join(DEFAULT_GPU_TYPES)),
        help="Comma-separated Runpod GPU type ids, in preferred order",
    )
    launch.add_argument(
        "--cloud-type",
        choices=("SECURE", "COMMUNITY"),
        default=os.getenv("RUNPOD_CLOUD_TYPE", "SECURE"),
    )
    launch.add_argument("--container-disk", type=int, default=int(os.getenv("RUNPOD_CONTAINER_GB", "50")))
    launch.add_argument("--volume-disk", type=int, default=int(os.getenv("RUNPOD_VOLUME_GB", "50")))
    launch.add_argument("--network-volume", default=os.getenv("RUNPOD_NETWORK_VOLUME_ID"))
    launch.add_argument("--spot", action="store_true", help="Use an interruptible Spot Pod")
    launch.add_argument("--timeout", type=int, default=2_400)
    launch.add_argument("--no-wait", action="store_true")
    launch.add_argument("--force-new", action="store_true")
    launch.set_defaults(handler=command_launch)

    status_parser = subparsers.add_parser("status", help="Show Pod and API status")
    status_parser.set_defaults(handler=command_status)

    start = subparsers.add_parser("start", help="Start the recorded Pod")
    start.add_argument("--timeout", type=int, default=2_400)
    start.add_argument("--no-wait", action="store_true")
    start.set_defaults(handler=command_start)

    stop = subparsers.add_parser("stop", help="Stop the recorded Pod")
    stop.set_defaults(handler=command_stop)

    terminate = subparsers.add_parser("terminate", help="Permanently delete the recorded Pod")
    terminate.add_argument("--yes", action="store_true")
    terminate.set_defaults(handler=command_terminate)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["launch"]
    args = make_parser().parse_args(argv)

    try:
        runpod_api_key = required_env("RUNPOD_API_KEY")
        client = RunpodClient(
            runpod_api_key,
            base_url=os.getenv("RUNPOD_API_BASE", "https://rest.runpod.io/v1"),
        )
        return args.handler(args, client, args.state_file.resolve())
    except LauncherError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Any newly created Pod was left running; use status or terminate.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
