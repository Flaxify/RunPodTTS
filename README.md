# IndexTTS Cloud for Runpod

> [!IMPORTANT]
> This repository is in early development. The current launcher is a tested prototype, not yet the promised one-click Gum and PowerShell experience. It will not create anything in Runpod unless you explicitly run the launcher with a configured account.

Launch an IndexTTS2 GPU Pod from WSL2, wait for it to become ready, and print the URL and API key that a local application can use.

## Gum frontend prototype

The new interactive launcher is being built in `start.sh`. Its current backend is deliberately fake: it lets us test the menus, price-sorted GPU choices, existing-Pod flow, lifecycle actions, and connection summary without creating or billing any Runpod resources.

```bash
./start.sh
```

If Gum is not already installed, the script downloads the pinned official Linux binary into the user's cache and verifies it against the release checksum. It does not use `sudo` or install a system package.

The prototype stores its simulated current-Pod card in `.runpodtts-demo-state`. Run `./start.sh --reset-demo` to clear only that local demo state.

The public address is provided by Runpod's HTTPS proxy:

```text
https://<pod-id>-8000.proxy.runpod.net
```

The default IndexTTS API key is intentionally simple:

```text
sk-1234notsecure
```

## What the launcher does

`launchIndex.sh` calls the Runpod REST API directly. It:

1. Creates a one-GPU Pod from the project's prebuilt image.
2. Tries several compatible 24 GB-or-larger NVIDIA GPU types.
3. Exposes the container's port `8000` through Runpod's HTTPS proxy.
4. Waits while the image starts, checkpoints download, and IndexTTS loads.
5. Prints `INDEXTTS_URL`, `INDEXTTS_API_KEY`, and the Pod ID.

It does not require SSH, Cloudflare Tunnel, Tailscale, Docker Compose, or Docker inside the Pod.

## One-time setup

### 1. Publish the container image

This repository includes [a GitHub Actions workflow](.github/workflows/docker.yml) that builds and publishes the image to GitHub Container Registry.

Push the repository to GitHub, run **Build IndexTTS Cloud image**, and make the resulting GHCR package public. Its address will look like:

```text
ghcr.io/YOUR_GITHUB_NAME/indextts_cloud:latest
```

Alternatively, build and push it from WSL2 with Docker:

```bash
docker build -t docker.io/YOUR_DOCKER_NAME/indextts-cloud:latest .
docker login
docker push docker.io/YOUR_DOCKER_NAME/indextts-cloud:latest
```

The build pins upstream IndexTTS to commit `13495845e3028f0bb6ca1462ad22aa0e76349e40`, the official model snapshot to `740dcaff396282ffb241903d150ac011cd4b1ede`, and uses CUDA 12.8. Model weights are downloaded to `/workspace` on the first Pod start, so later starts reuse them.

### 2. Configure WSL2

```bash
cp .env.example .env
nano .env
chmod +x launchIndex.sh
```

Set these two values in `.env`:

```dotenv
RUNPOD_API_KEY=your-real-runpod-api-key
INDEXTTS_IMAGE=ghcr.io/YOUR_GITHUB_NAME/indextts_cloud:latest
```

`RUNPOD_API_KEY` is the only sensitive credential. Do not commit `.env`.

## Launch

From WSL2:

```bash
./launchIndex.sh
```

The shell file is only a convenience wrapper. The launcher uses Python's standard library, so this is equivalent:

```bash
python3 launchIndex.py launch
```

The first start can take a while because Runpod must pull the large CUDA image and download the IndexTTS checkpoints. The final output looks like:

```text
INDEXTTS_URL=https://abc123-8000.proxy.runpod.net
INDEXTTS_API_KEY=sk-1234notsecure
RUNPOD_POD_ID=abc123
```

The launcher records the active Pod in `.runpod-index.json` to prevent accidental duplicate Pods.

## Manage the Pod

```bash
./launchIndex.sh status
./launchIndex.sh stop
./launchIndex.sh start
./launchIndex.sh terminate --yes
```

`stop` releases the GPU while retaining the Pod's `/workspace` volume. `terminate --yes` permanently deletes the Pod and its attached Pod volume.

Useful launch overrides:

```bash
./launchIndex.sh launch --gpu-types "NVIDIA GeForce RTX 4090,NVIDIA GeForce RTX 3090"
./launchIndex.sh launch --cloud-type COMMUNITY
./launchIndex.sh launch --spot
./launchIndex.sh launch --no-wait
```

## API

Interactive documentation is available at:

```text
https://<pod-id>-8000.proxy.runpod.net/docs
```

Authentication accepts either header:

```http
Authorization: Bearer sk-1234notsecure
X-API-Key: sk-1234notsecure
```

### Upload a reusable reference voice

```bash
curl "$INDEXTTS_URL/v1/voices" \
  -H "Authorization: Bearer $INDEXTTS_API_KEY" \
  -F "voice_id=default" \
  -F "file=@voice-reference.wav"
```

Reference audio is fundamental to IndexTTS voice cloning. The current upstream repository does not bundle an example voice, so upload one clip after the first deployment. It persists in `/workspace/indextts/voices` across Pod stops and starts.

You can upload additional voices the same way with IDs such as `hero` or `narrator`.

### Generate speech

```bash
curl "$INDEXTTS_URL/v1/audio/speech" \
  -H "Authorization: Bearer $INDEXTTS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"indextts-2","input":"Hello from the cloud.","voice":"default"}' \
  --output speech.wav
```

`POST /tts` is an alias for the same request. Change `"voice":"default"` to another uploaded voice ID when needed.

### Health and discovery

```text
GET /healthz       process health; no key required
GET /readyz        model readiness; no key required
GET /v1/info       capabilities and saved voices
GET /v1/models     OpenAI-style model listing
GET /v1/voices     saved voice listing
POST /v1/voices    upload or replace a reference voice
POST /v1/audio/speech
POST /tts
```

WAV, MP3, Opus, and FLAC output are supported through the `response_format` field. Normal game dialogue should fit Runpod's HTTP proxy timeout; very long narration should be split into shorter requests.

## Local verification

The API tests use a fake TTS engine and do not download models or require a GPU:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

Actual IndexTTS inference, CUDA compatibility, and first-boot duration still need one real Runpod GPU test after the image is published.
