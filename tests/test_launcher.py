from __future__ import annotations

import argparse
import json

from launchIndex import (
    DEFAULT_INDEXTTS_API_KEY,
    DeploymentState,
    build_create_payload,
    endpoint_for,
)


def test_endpoint_uses_runpod_https_proxy() -> None:
    assert endpoint_for("abc123") == "https://abc123-8000.proxy.runpod.net"


def test_deployment_state_round_trip(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    state = DeploymentState(
        pod_id="pod-1",
        endpoint=endpoint_for("pod-1"),
        index_api_key=DEFAULT_INDEXTTS_API_KEY,
        image="ghcr.io/example/indextts-cloud:latest",
        created_at="2026-07-27T00:00:00+00:00",
    )

    state.save(state_file)

    assert DeploymentState.load(state_file) == state
    assert json.loads(state_file.read_text())["pod_id"] == "pod-1"


def test_create_payload_exposes_api_and_uses_multiple_gpu_types() -> None:
    args = argparse.Namespace(
        gpu_types="NVIDIA GeForce RTX 4090,NVIDIA GeForce RTX 3090",
        name="index-test",
        cloud_type="SECURE",
        container_disk=50,
        network_volume=None,
        volume_disk=50,
        spot=False,
    )

    payload = build_create_payload(
        "ghcr.io/example/indextts-cloud:latest",
        DEFAULT_INDEXTTS_API_KEY,
        args,
    )

    assert payload["ports"] == ["8000/http"]
    assert payload["allowedCudaVersions"] == ["12.8", "12.9", "13.0"]
    assert payload["gpuTypePriority"] == "availability"
    assert payload["gpuTypeIds"] == [
        "NVIDIA GeForce RTX 4090",
        "NVIDIA GeForce RTX 3090",
    ]
    assert payload["env"]["INDEXTTS_API_KEY"] == DEFAULT_INDEXTTS_API_KEY
    assert payload["volumeInGb"] == 50
