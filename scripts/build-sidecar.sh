#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="${REPO_DIR}/python/.venv-sidecar"
DIST_ROOT="${REPO_DIR}/python/dist"
DIST_DIR="${DIST_ROOT}/sber-whisper-sidecar"
BUILD_DIR="${REPO_DIR}/python/build"
SCRIPT_PATH="${REPO_DIR}/python/asr_service.py"
GIGAAM_REF="gigaam @ git+https://github.com/salute-developers/GigaAM.git@94082238aa5cabbd4bdc28e755100a1922a90d43"

if [[ ! -f "${SCRIPT_PATH}" ]]; then
  echo "Missing sidecar source: ${SCRIPT_PATH}" >&2
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

PY="${VENV_DIR}/bin/python"
"${PY}" -m pip install --upgrade pip wheel setuptools
"${PY}" -m pip install -r "${REPO_DIR}/python/requirements.txt" pyinstaller
"${PY}" -m pip install --force-reinstall --no-deps --no-cache-dir "${GIGAAM_REF}"

rm -rf "${DIST_DIR}" "${BUILD_DIR}"
mkdir -p "${DIST_ROOT}"

"${PY}" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name sber-whisper-sidecar \
  --distpath "${DIST_ROOT}" \
  --workpath "${BUILD_DIR}" \
  --specpath "${BUILD_DIR}" \
  --collect-all gigaam \
  --collect-all torch \
  --collect-all torchaudio \
  --collect-data sounddevice \
  --collect-binaries sounddevice \
  --collect-data soundfile \
  --collect-binaries soundfile \
  "${SCRIPT_PATH}"

if [[ ! -f "${DIST_DIR}/sber-whisper-sidecar" ]]; then
  echo "Sidecar binary was not created: ${DIST_DIR}/sber-whisper-sidecar" >&2
  exit 1
fi

echo "Built sidecar: ${DIST_DIR}/sber-whisper-sidecar"
