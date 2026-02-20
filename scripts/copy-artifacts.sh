#!/usr/bin/env bash
set -euo pipefail

PLATFORM="${1:-}"
if [[ -z "${PLATFORM}" ]]; then
  echo "Usage: $0 <windows|macos>"
  exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${REPO_DIR}/dist/releases"
mkdir -p "${OUT_DIR}"

if [[ "${PLATFORM}" == "windows" ]]; then
  SRC="${REPO_DIR}/src-tauri/target/release/bundle/nsis"
  cp -f "${SRC}"/*.exe "${OUT_DIR}"/
elif [[ "${PLATFORM}" == "macos" ]]; then
  SRC="${REPO_DIR}/src-tauri/target/release/bundle/dmg"
  cp -f "${SRC}"/*.dmg "${OUT_DIR}"/
else
  echo "Unsupported platform: ${PLATFORM}"
  exit 1
fi

echo "Artifacts copied to ${OUT_DIR}"
