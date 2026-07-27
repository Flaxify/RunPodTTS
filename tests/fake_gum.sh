#!/usr/bin/env bash
set -Eeuo pipefail

command_name="${1:-}"
shift || true

case "${command_name}" in
  style)
    printf '%s\n' "${*: -1}"
    ;;
  choose)
    arguments="$*"
    case "${arguments}" in
      *"WHAT DO YOU WANT TO DO?"*) printf 'Setup\n' ;;
      *"SETUP SOURCE"*) printf 'Secure Cloud\n' ;;
      *"DEMO SECURE offers"*) printf '[secure-a5000]\n' ;;
      *"Storage behavior"*) printf '50 GB\n' ;;
      *"Back to main menu"*) printf 'Exit\n' ;;
      *) exit 2 ;;
    esac
    ;;
  input)
    arguments="$*"
    case "${arguments}" in
      *"Pod name:"*) printf 'RunPodTTS\n' ;;
      *"IndexTTS key:"*) printf 'sk-demo-ui\n' ;;
      *) printf '\n' ;;
    esac
    ;;
  confirm|spin)
    exit 0
    ;;
  --version)
    printf 'fake gum for tests\n'
    ;;
  *)
    exit 2
    ;;
esac
