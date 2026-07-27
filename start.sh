#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${RUNPODTTS_ENV_FILE:-${SCRIPT_DIR}/.env}"
STATE_FILE="${RUNPODTTS_STATE_FILE:-${SCRIPT_DIR}/.runpodtts-demo-state}"
GUM_VERSION="${RUNPODTTS_GUM_VERSION:-0.17.0}"
GUM_BIN="${RUNPODTTS_GUM:-}"

readonly ACCENT="#7D56F4"
readonly GOOD="#35BB9A"
readonly WARN="#FFB454"
readonly BAD="#FF5F87"
readonly MUTED="#767676"
readonly UI_WIDTH=82

RUNPOD_API_KEY="${RUNPOD_API_KEY:-}"
INDEXTTS_API_KEY="${INDEXTTS_API_KEY:-}"
RUNPOD_KEY_SOURCE="environment"
REQUEST_EXIT=0

POD_ID=""
POD_NAME=""
POD_SOURCE=""
POD_GPU=""
POD_VRAM=""
POD_STATUS=""
POD_RATE=""
POD_INDEX_KEY=""
POD_URL=""
POD_STORAGE=""

SELECTED_ID=""
SELECTED_NAME=""
SELECTED_SOURCE=""
SELECTED_GPU=""
SELECTED_VRAM=""
SELECTED_STATUS=""
SELECTED_RATE=""

readonly -a SECURE_OFFERS=(
  "0.27|secure-a5000|NVIDIA RTX A5000|24 GB|Available"
  "0.44|secure-4090|NVIDIA GeForce RTX 4090|24 GB|Available"
  "0.79|secure-l40s|NVIDIA L40S|48 GB|Limited"
)

readonly -a COMMUNITY_OFFERS=(
  "0.22|community-3090|NVIDIA GeForce RTX 3090|24 GB|Available"
  "0.31|community-a5000|NVIDIA RTX A5000|24 GB|Available"
  "0.39|community-4090|NVIDIA GeForce RTX 4090|24 GB|Limited"
)

readonly -a EXISTING_PODS=(
  "0.29|demo-pod-7f3a|Game voices|SECURE|NVIDIA RTX A5000|24 GB|STOPPED"
  "0.44|demo-pod-a91c|Narrator lab|COMMUNITY|NVIDIA GeForce RTX 4090|24 GB|RUNNING"
  "0.79|demo-pod-c24e|Audio experiments|SECURE|NVIDIA L40S|48 GB|RUNNING"
)

plain_error() {
  printf 'RunPodTTS: %s\n' "$*" >&2
}

die() {
  if [[ -n "${GUM_BIN}" && -x "${GUM_BIN}" ]]; then
    "${GUM_BIN}" style --foreground "${BAD}" --bold "Error: $*" >&2
  else
    plain_error "$*"
  fi
  exit 1
}

usage() {
  cat <<'EOF'
RunPodTTS frontend prototype

Usage:
  ./start.sh              Open the Gum interface
  ./start.sh --demo       Open the Gum interface (same as the default for now)
  ./start.sh --doctor     Verify or bootstrap the Gum dependency
  ./start.sh --reset-demo Remove only the local simulated Pod state
  ./start.sh --help       Show this help

This build does not call RunPod. GPU offers, Pods, deployment progress, and
lifecycle actions are simulated so the interface can be designed safely.
EOF
}

bootstrap_gum() {
  local os arch release_arch asset cache_dir temp_dir archive checksums checksum_line extracted

  os="$(uname -s)"
  arch="$(uname -m)"
  [[ "${os}" == "Linux" ]] || die "automatic Gum setup currently supports Linux/WSL only."

  case "${arch}" in
    x86_64|amd64) release_arch="x86_64" ;;
    aarch64|arm64) release_arch="arm64" ;;
    *) die "unsupported CPU architecture for Gum: ${arch}" ;;
  esac

  for command_name in curl tar; do
    command -v "${command_name}" >/dev/null 2>&1 || die "${command_name} is required to download Gum."
  done
  if ! command -v sha256sum >/dev/null 2>&1; then
    die "sha256sum is required to verify the Gum download."
  fi

  cache_dir="${XDG_CACHE_HOME:-${HOME}/.cache}/runpodtts/bin"
  asset="gum_${GUM_VERSION}_Linux_${release_arch}.tar.gz"
  temp_dir="$(mktemp -d)"
  archive="${temp_dir}/${asset}"
  checksums="${temp_dir}/checksums.txt"

  printf 'Gum was not found. Downloading verified Gum v%s to %s\n' "${GUM_VERSION}" "${cache_dir}"
  if ! curl --fail --silent --show-error --location \
    "https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}/${asset}" \
    --output "${archive}"; then
    rm -rf -- "${temp_dir}"
    die "could not download ${asset}."
  fi
  if ! curl --fail --silent --show-error --location \
    "https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}/checksums.txt" \
    --output "${checksums}"; then
    rm -rf -- "${temp_dir}"
    die "could not download the Gum checksum list."
  fi

  checksum_line="$(grep -E "[[:space:]]${asset}$" "${checksums}" || true)"
  [[ -n "${checksum_line}" ]] || {
    rm -rf -- "${temp_dir}"
    die "the Gum checksum list did not contain ${asset}."
  }
  printf '%s\n' "${checksum_line}" > "${temp_dir}/asset.sha256"
  if ! (cd -- "${temp_dir}" && sha256sum --check --status asset.sha256); then
    rm -rf -- "${temp_dir}"
    die "Gum checksum verification failed."
  fi

  tar -xzf "${archive}" -C "${temp_dir}"
  extracted="$(find "${temp_dir}" -maxdepth 2 -type f -name gum -print -quit)"
  [[ -n "${extracted}" ]] || {
    rm -rf -- "${temp_dir}"
    die "the Gum archive did not contain the expected binary."
  }

  mkdir -p -- "${cache_dir}"
  install -m 0755 -- "${extracted}" "${cache_dir}/gum"
  rm -rf -- "${temp_dir}"
  GUM_BIN="${cache_dir}/gum"
}

ensure_gum() {
  if [[ -n "${GUM_BIN}" ]]; then
    [[ -x "${GUM_BIN}" ]] || die "RUNPODTTS_GUM is not executable: ${GUM_BIN}"
    return
  fi
  if command -v gum >/dev/null 2>&1; then
    GUM_BIN="$(command -v gum)"
    return
  fi

  local cached_gum
  cached_gum="${XDG_CACHE_HOME:-${HOME}/.cache}/runpodtts/bin/gum"
  if [[ -x "${cached_gum}" ]]; then
    GUM_BIN="${cached_gum}"
    return
  fi
  bootstrap_gum
}

read_env_value() {
  local wanted="$1" line key value result=""
  [[ -f "${ENV_FILE}" ]] || return 0

  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    if [[ "${line}" == export[[:space:]]* ]]; then
      line="${line#export}"
      line="${line#"${line%%[![:space:]]*}"}"
    fi
    [[ "${line}" == *=* ]] || continue
    key="${line%%=*}"
    key="${key//[[:space:]]/}"
    [[ "${key}" == "${wanted}" ]] || continue
    value="${line#*=}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ "${value}" == \"*\" && "${value}" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "${value}" == \'*\' && "${value}" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    result="${value}"
  done < "${ENV_FILE}"
  printf '%s' "${result}"
}

looks_like_placeholder() {
  case "$1" in
    ""|replace-*|your-*|changeme|CHANGE_ME) return 0 ;;
    *) return 1 ;;
  esac
}

persist_runpod_key() {
  local key="$1"
  umask 077
  if [[ -s "${ENV_FILE}" ]]; then
    printf '\n# Added by RunPodTTS start.sh\nRUNPOD_API_KEY=%s\n' "${key}" >> "${ENV_FILE}"
  else
    printf '# RunPodTTS local configuration\nRUNPOD_API_KEY=%s\n' "${key}" > "${ENV_FILE}"
  fi
  chmod 600 "${ENV_FILE}"
}

ensure_runpod_key() {
  local from_file entered

  if looks_like_placeholder "${RUNPOD_API_KEY}"; then
    from_file="$(read_env_value RUNPOD_API_KEY)"
    if ! looks_like_placeholder "${from_file}"; then
      RUNPOD_API_KEY="${from_file}"
      RUNPOD_KEY_SOURCE=".env"
    fi
  fi
  if ! looks_like_placeholder "${RUNPOD_API_KEY}"; then
    return
  fi

  "${GUM_BIN}" style \
    --border rounded --border-foreground "${WARN}" --padding "1 2" --width "${UI_WIDTH}" \
    "RunPod API key required" \
    "This frontend prototype never transmits the key. Enter any non-empty value to test the UI."

  while true; do
    if ! entered="$("${GUM_BIN}" input --password --width 64 --prompt "Key: " --placeholder "RunPod API key")"; then
      exit 0
    fi
    entered="${entered//$'\r'/}"
    entered="${entered//$'\n'/}"
    [[ -n "${entered}" ]] && break
    "${GUM_BIN}" style --foreground "${BAD}" "A key is required to continue."
  done
  RUNPOD_API_KEY="${entered}"
  RUNPOD_KEY_SOURCE="this session"

  if "${GUM_BIN}" confirm "Save this key in the ignored .env file?"; then
    persist_runpod_key "${RUNPOD_API_KEY}"
    RUNPOD_KEY_SOURCE=".env"
  fi
}

mask_key() {
  local key="$1"
  if ((${#key} <= 4)); then
    printf '••••%s' "${key}"
  else
    printf '••••%s' "${key: -4}"
  fi
}

reset_state_variables() {
  POD_ID=""
  POD_NAME=""
  POD_SOURCE=""
  POD_GPU=""
  POD_VRAM=""
  POD_STATUS=""
  POD_RATE=""
  POD_INDEX_KEY=""
  POD_URL=""
  POD_STORAGE=""
}

load_state() {
  local version=""
  reset_state_variables
  [[ -f "${STATE_FILE}" ]] || return 0
  IFS=$'\t' read -r version POD_ID POD_NAME POD_SOURCE POD_GPU POD_VRAM POD_STATUS POD_RATE POD_INDEX_KEY POD_URL POD_STORAGE < "${STATE_FILE}" || true
  if [[ "${version}" != "1" || -z "${POD_ID}" ]]; then
    reset_state_variables
  fi
}

sanitize_state_value() {
  local value="$1"
  value="${value//$'\t'/ }"
  value="${value//$'\r'/ }"
  value="${value//$'\n'/ }"
  printf '%s' "${value}"
}

save_state() {
  umask 077
  printf '1\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$(sanitize_state_value "${POD_ID}")" \
    "$(sanitize_state_value "${POD_NAME}")" \
    "$(sanitize_state_value "${POD_SOURCE}")" \
    "$(sanitize_state_value "${POD_GPU}")" \
    "$(sanitize_state_value "${POD_VRAM}")" \
    "$(sanitize_state_value "${POD_STATUS}")" \
    "$(sanitize_state_value "${POD_RATE}")" \
    "$(sanitize_state_value "${POD_INDEX_KEY}")" \
    "$(sanitize_state_value "${POD_URL}")" \
    "$(sanitize_state_value "${POD_STORAGE}")" > "${STATE_FILE}"
  chmod 600 "${STATE_FILE}"
}

clear_screen() {
  if [[ -t 1 && "${RUNPODTTS_NO_CLEAR:-0}" != "1" ]]; then
    printf '\033[2J\033[H'
  fi
}

render_header() {
  clear_screen
  "${GUM_BIN}" style \
    --foreground "${ACCENT}" --border double --border-foreground "${ACCENT}" \
    --bold --align center --padding "1 2" --width "${UI_WIDTH}" \
    "RunPodTTS" \
    "IndexTTS on RunPod without the installation headache"
  "${GUM_BIN}" style --foreground "${WARN}" --bold \
    "FRONTEND PROTOTYPE · NO RUNPOD API CALLS"
  printf '\n'
}

render_current_setup() {
  local content status_line rate_line
  if [[ -z "${POD_ID}" ]]; then
    content=$'CURRENT SETUP\n\nNo Pod is managed yet. Choose Setup to walk through the demo flow.'
    "${GUM_BIN}" style \
      --border rounded --border-foreground "${MUTED}" --padding "1 2" --width "${UI_WIDTH}" \
      "${content}"
    return
  fi

  if [[ "${POD_STATUS}" == "RUNNING" ]]; then
    status_line="RUNNING (simulated API status)"
    rate_line="\$${POD_RATE}/hr GPU · storage billed separately"
  else
    status_line="STOPPED (simulated API status)"
    rate_line="\$0.00/hr GPU · persistent storage may still be billed"
  fi

  content="$(printf '%s\n\n%-15s %s\n%-15s %s\n%-15s %s (%s)\n%-15s %s\n%-15s %s\n%-15s %s\n%-15s %s\n%-15s %s' \
    "CURRENT SETUP" \
    "Pod" "${POD_NAME}  [${POD_ID}]" \
    "Status" "${status_line}" \
    "GPU" "${POD_GPU}" "${POD_VRAM}" \
    "Source" "${POD_SOURCE}" \
    "Cost now" "${rate_line}" \
    "Storage" "${POD_STORAGE}" \
    "Index API key" "${POD_INDEX_KEY}" \
    "Endpoint" "${POD_URL}")"

  "${GUM_BIN}" style \
    --border rounded --border-foreground "${GOOD}" --padding "1 2" --width "${UI_WIDTH}" \
    "${content}"
}

render_account_line() {
  "${GUM_BIN}" style --foreground "${MUTED}" \
    "RunPod account: $(mask_key "${RUNPOD_API_KEY}") (${RUNPOD_KEY_SOURCE})"
  printf '\n'
}

pause_for_menu() {
  "${GUM_BIN}" input --width 46 --prompt "" --placeholder "Press Enter to return to the menu" >/dev/null || true
}

notice() {
  local color="$1"
  shift
  "${GUM_BIN}" style \
    --border rounded --border-foreground "${color}" --padding "1 2" --width "${UI_WIDTH}" \
    "$*"
}

sorted_offer_records() {
  local source="$1"
  case "${source}" in
    SECURE) printf '%s\n' "${SECURE_OFFERS[@]}" ;;
    COMMUNITY) printf '%s\n' "${COMMUNITY_OFFERS[@]}" ;;
    EXISTING) printf '%s\n' "${EXISTING_PODS[@]}" ;;
    *) return 1 ;;
  esac | LC_ALL=C sort -t '|' -k1,1n
}

select_new_offer() {
  local source="$1" record rate id gpu vram availability selection selected_id
  local -a records=() labels=()

  mapfile -t records < <(sorted_offer_records "${source}")
  for record in "${records[@]}"; do
    IFS='|' read -r rate id gpu vram availability <<< "${record}"
    labels+=("$(printf '$%-7s  %-29s  %-6s  %-10s  [%s]' "${rate}/hr" "${gpu}" "${vram}" "${availability}" "${id}")")
  done

  if ! selection="$("${GUM_BIN}" choose \
    --height 10 \
    --header "DEMO ${source} offers · placeholder prices · sorted low to high" \
    "${labels[@]}" "Back")"; then
    return 1
  fi
  [[ "${selection}" != "Back" ]] || return 1
  selected_id="${selection##*[}"
  selected_id="${selected_id%]}"

  for record in "${records[@]}"; do
    IFS='|' read -r rate id gpu vram availability <<< "${record}"
    if [[ "${id}" == "${selected_id}" ]]; then
      SELECTED_ID="${id}"
      SELECTED_NAME=""
      SELECTED_SOURCE="${source} CLOUD"
      SELECTED_GPU="${gpu}"
      SELECTED_VRAM="${vram}"
      SELECTED_STATUS="AVAILABLE"
      SELECTED_RATE="${rate}"
      return 0
    fi
  done
  return 1
}

select_existing_pod() {
  local record rate id name cloud gpu vram status selection selected_id
  local -a records=() labels=()

  mapfile -t records < <(sorted_offer_records EXISTING)
  for record in "${records[@]}"; do
    IFS='|' read -r rate id name cloud gpu vram status <<< "${record}"
    labels+=("$(printf '$%-7s  %-16s  %-9s  %-25s  [%s]' "${rate}/hr" "${name}" "${status}" "${gpu}" "${id}")")
  done

  if ! selection="$("${GUM_BIN}" choose \
    --height 10 \
    --header "DEMO Pods on this API key · configured GPU price · sorted low to high" \
    "${labels[@]}" "Back")"; then
    return 1
  fi
  [[ "${selection}" != "Back" ]] || return 1
  selected_id="${selection##*[}"
  selected_id="${selected_id%]}"

  for record in "${records[@]}"; do
    IFS='|' read -r rate id name cloud gpu vram status <<< "${record}"
    if [[ "${id}" == "${selected_id}" ]]; then
      SELECTED_ID="${id}"
      SELECTED_NAME="${name}"
      SELECTED_SOURCE="EXISTING · ${cloud} CLOUD"
      SELECTED_GPU="${gpu}"
      SELECTED_VRAM="${vram}"
      SELECTED_STATUS="${status}"
      SELECTED_RATE="${rate}"
      return 0
    fi
  done
  return 1
}

prompt_index_key() {
  local default_key entered
  default_key="${INDEXTTS_API_KEY}"
  if looks_like_placeholder "${default_key}"; then
    default_key="$(read_env_value INDEXTTS_API_KEY)"
  fi
  if looks_like_placeholder "${default_key}"; then
    default_key="sk-1234notsecure"
  fi

  if ! entered="$("${GUM_BIN}" input \
    --width 64 --prompt "IndexTTS key: " --value "${default_key}")"; then
    return 1
  fi
  entered="${entered//$'\r'/}"
  entered="${entered//$'\n'/}"
  [[ -n "${entered}" ]] || return 1
  POD_INDEX_KEY="${entered}"
}

prompt_pod_name() {
  local entered
  if ! entered="$("${GUM_BIN}" input \
    --width 64 --prompt "Pod name: " --value "RunPodTTS")"; then
    return 1
  fi
  entered="$(sanitize_state_value "${entered}")"
  [[ -n "${entered}" ]] || entered="RunPodTTS"
  POD_NAME="${entered}"
}

prompt_storage() {
  local choice
  if ! choice="$("${GUM_BIN}" choose \
    --header "Storage behavior" \
    "50 GB persistent Pod volume · faster restarts · billed while stopped" \
    "Ephemeral container disk · no stopped storage charge · redownload models" \
    "Back")"; then
    return 1
  fi
  case "${choice}" in
    "50 GB"*) POD_STORAGE="50 GB persistent Pod volume" ;;
    "Ephemeral"*) POD_STORAGE="Ephemeral container disk" ;;
    *) return 1 ;;
  esac
}

simulate_setup() {
  local suffix
  "${GUM_BIN}" spin --spinner dot --title "[DEMO] Checking Pod compatibility..." -- sleep 0.45
  "${GUM_BIN}" spin --spinner dot --title "[DEMO] Installing the RunPodTTS service..." -- sleep 0.65
  "${GUM_BIN}" spin --spinner dot --title "[DEMO] Waiting for IndexTTS..." -- sleep 0.55

  if [[ "${SELECTED_SOURCE}" == EXISTING* ]]; then
    POD_ID="${SELECTED_ID}"
  else
    suffix="$(date +%s)"
    POD_ID="demo-${suffix: -8}"
  fi
  POD_SOURCE="${SELECTED_SOURCE}"
  POD_GPU="${SELECTED_GPU}"
  POD_VRAM="${SELECTED_VRAM}"
  POD_STATUS="RUNNING"
  POD_RATE="${SELECTED_RATE}"
  POD_URL="https://${POD_ID}-8000.proxy.runpod.net"
  save_state
}

review_and_setup() {
  local review choice

  if [[ "${SELECTED_SOURCE}" == EXISTING* ]]; then
    POD_NAME="${SELECTED_NAME}"
    POD_STORAGE="Existing Pod storage configuration"
  else
    prompt_pod_name || return 0
    prompt_storage || return 0
  fi
  prompt_index_key || return 0

  review="$(printf '%-17s %s\n%-17s %s\n%-17s %s (%s)\n%-17s $%s/hr (demo)\n%-17s %s\n%-17s %s' \
    "Pod" "${POD_NAME}" \
    "Source" "${SELECTED_SOURCE}" \
    "GPU" "${SELECTED_GPU}" "${SELECTED_VRAM}" \
    "GPU price" "${SELECTED_RATE}" \
    "Storage" "${POD_STORAGE}" \
    "Index API key" "${POD_INDEX_KEY}")"

  render_header
  render_current_setup
  printf '\n'
  notice "${ACCENT}" "SETUP REVIEW"$'\n\n'"${review}"$'\n\n'"Nothing real will be created in this frontend prototype."
  if ! "${GUM_BIN}" confirm "Run the simulated setup?"; then
    return 0
  fi

  simulate_setup
  load_state
  render_header
  render_current_setup
  printf '\n'
  notice "${GOOD}" "SETUP COMPLETE (DEMO)"$'\n\n'"IndexTTS URL: ${POD_URL}"$'\n'"IndexTTS API key: ${POD_INDEX_KEY}"

  if choice="$("${GUM_BIN}" choose "Back to main menu" "Exit")"; then
    [[ "${choice}" == "Back to main menu" ]] || REQUEST_EXIT=1
  else
    REQUEST_EXIT=1
  fi
}

setup_menu() {
  local choice

  if [[ -n "${POD_ID}" ]]; then
    notice "${WARN}" \
      "A Pod is already managed by this setup. Delete current first so a new setup cannot accidentally orphan a billed Pod."
    pause_for_menu
    return
  fi

  while true; do
    render_header
    render_current_setup
    render_account_line
    if ! choice="$("${GUM_BIN}" choose \
      --header "SETUP SOURCE" \
      "Secure Cloud" \
      "Community Cloud" \
      "Existing Pod" \
      "Back")"; then
      return
    fi
    case "${choice}" in
      "Secure Cloud") select_new_offer SECURE && review_and_setup; return ;;
      "Community Cloud") select_new_offer COMMUNITY && review_and_setup; return ;;
      "Existing Pod") select_existing_pod && review_and_setup; return ;;
      "Back") return ;;
    esac
  done
}

stop_current() {
  [[ -n "${POD_ID}" ]] || return
  [[ "${POD_STATUS}" != "STOPPED" ]] || return

  notice "${WARN}" \
    "Stopping releases GPU compute. Persistent Pod or network storage can still be billed while the Pod is stopped."
  if ! "${GUM_BIN}" confirm "Stop ${POD_NAME} (${POD_ID})?"; then
    return
  fi
  "${GUM_BIN}" spin --spinner dot --title "[DEMO] Stopping ${POD_NAME}..." -- sleep 0.5
  POD_STATUS="STOPPED"
  save_state
  notice "${GOOD}" "${POD_NAME} is now STOPPED (simulated)."
  pause_for_menu
}

start_current() {
  [[ -n "${POD_ID}" ]] || return
  [[ "${POD_STATUS}" != "RUNNING" ]] || return

  if ! "${GUM_BIN}" confirm "Start ${POD_NAME} (${POD_ID})?"; then
    return
  fi
  "${GUM_BIN}" spin --spinner dot --title "[DEMO] Starting ${POD_NAME}..." -- sleep 0.5
  POD_STATUS="RUNNING"
  save_state
  notice "${GOOD}" "${POD_NAME} is now RUNNING (simulated)."$'\n\n'"IndexTTS URL: ${POD_URL}"
  pause_for_menu
}

delete_current() {
  [[ -n "${POD_ID}" ]] || return

  notice "${BAD}" \
    "DELETE CURRENT"$'\n\n'"Production behavior will terminate only ${POD_NAME} [${POD_ID}] and its attached Pod volume. This demo only removes simulated state."
  if ! "${GUM_BIN}" confirm "Delete the current setup?"; then
    return
  fi
  "${GUM_BIN}" spin --spinner dot --title "[DEMO] Deleting ${POD_NAME}..." -- sleep 0.5
  rm -f -- "${STATE_FILE}"
  reset_state_variables
  notice "${GOOD}" "Current simulated setup deleted. The RunPod API key in .env was not changed."
  pause_for_menu
}

refresh_current() {
  "${GUM_BIN}" spin --spinner dot --title "[DEMO] Refreshing status from the fake backend..." -- sleep 0.4
  load_state
}

main_menu() {
  local choice
  local -a options

  while ((REQUEST_EXIT == 0)); do
    load_state
    render_header
    render_current_setup
    render_account_line

    options=("Setup")
    if [[ -n "${POD_ID}" && "${POD_STATUS}" == "RUNNING" ]]; then
      options+=("Stop current Pod")
    elif [[ -n "${POD_ID}" && "${POD_STATUS}" == "STOPPED" ]]; then
      options+=("Start current Pod")
    fi
    if [[ -n "${POD_ID}" ]]; then
      options+=("Delete current setup" "Refresh status")
    fi
    options+=("Exit")

    if ! choice="$("${GUM_BIN}" choose --header "WHAT DO YOU WANT TO DO?" "${options[@]}")"; then
      break
    fi
    case "${choice}" in
      "Setup") setup_menu ;;
      "Stop current Pod") stop_current ;;
      "Start current Pod") start_current ;;
      "Delete current setup") delete_current ;;
      "Refresh status") refresh_current ;;
      "Exit") break ;;
    esac
  done
}

main() {
  case "${1:-}" in
    ""|--demo) ;;
    --help|-h) usage; return 0 ;;
    --doctor)
      ensure_gum
      printf 'Gum: '
      "${GUM_BIN}" --version
      printf 'Backend: frontend demo only (no RunPod API calls)\n'
      return 0
      ;;
    --reset-demo)
      rm -f -- "${STATE_FILE}"
      printf 'Removed simulated state: %s\n' "${STATE_FILE}"
      return 0
      ;;
    *) usage >&2; return 2 ;;
  esac

  ensure_gum
  ensure_runpod_key
  if looks_like_placeholder "${INDEXTTS_API_KEY}"; then
    INDEXTTS_API_KEY="$(read_env_value INDEXTTS_API_KEY)"
  fi
  load_state
  main_menu
  clear_screen
  "${GUM_BIN}" style --foreground "${ACCENT}" --bold "RunPodTTS frontend demo closed."
}

if [[ "${RUNPODTTS_SOURCE_ONLY:-0}" != "1" ]]; then
  main "$@"
fi
