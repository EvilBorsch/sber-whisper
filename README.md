# Sber Whisper Desktop

Cross-platform desktop voice-to-text app (Windows + macOS) with:
- Tray/top-bar background mode
- Global hold-to-talk hotkey (`Ctrl+G` on Windows, `Cmd+G` on macOS)
- Siri-style popup with streaming partials and final transcription
- Automatic clipboard copy on final result
- Local-only processing with GigaAM `v3_e2e_rnnt`
- Bundled Python sidecar in installer (target machine does not need Python)

## Stack
- Desktop shell: Tauri v2 + React + TypeScript
- ASR sidecar: Python (`python/asr_service.py`)
- Model: `gigaam.load_model("v3_e2e_rnnt")`
- GigaAM source: GitHub `salute-developers/GigaAM` (PyPI `0.1.0` is too old for `v3_e2e_rnnt`)

## Prerequisites
- Node.js 20+
- Rust toolchain (stable)
- Python 3.10+
- Windows only: Visual Studio 2022 with `Desktop development with C++` and Windows 10/11 SDK
- On Windows with CUDA: NVIDIA drivers + CUDA-compatible PyTorch build

Only the build machine needs Python. End users install via `.exe`/`.dmg` and do not need Python.

## Quick Start
```bash
make setup
make dev
```

## Local Debug Without Installer (Windows)
If you want to debug the app locally without using installer and without `localhost` errors:

```bash
npm run run-local-win
```

This builds a local debug exe with embedded frontend and runs:
`src-tauri/target/debug/sber-whisper.exe`

By default, this command rebuilds the sidecar every run, so dependency updates are applied.

For local GPU debug sidecar build:

```bash
set SIDECAR_VARIANT=gpu && npm run run-local-win
```

## Build Artifacts
`make release` builds for the current host OS:
- Windows host -> NSIS `.exe`
- macOS host -> `.dmg`

Output artifacts are copied to `artifacts/releases`.

The release build first creates a standalone ASR sidecar binary (`sber-whisper-sidecar`) and
embeds it into the installer resources, so you can share just the installer file.

Windows installer is CPU-first by default, so resulting `setup.exe` stays smaller and stable for sharing.

Manual targets:
```bash
make release-win
make release-mac
```

## Optional Windows GPU Build
GPU variant is separate from installer build.

Build GPU portable package (no installer):
```bash
make release-win-gpu
```

Result:
- folder: `artifacts/releases/sber-whisper-gpu-portable-win-x64`
- zip: `artifacts/releases/sber-whisper-gpu-portable-win-x64.zip`

Run GPU portable build:
1. Unzip package.
2. Keep `sber-whisper.exe` and `sber-whisper-sidecar/` in the same folder.
3. Start `sber-whisper.exe`.

Build only GPU sidecar (without packaging):
```bash
make gpu-sidecar-win
```

## Build On macOS
Run these commands on a Mac host:

```bash
xcode-select --install
brew install node python@3.11 rustup-init
rustup-init -y
```

Then from the project directory:

```bash
make setup
make release-mac
```

Resulting `.dmg` is copied to `artifacts/releases`.

## Runtime Behavior
- App starts hidden in tray/top-bar.
- Hold global hotkey to record; release to transcribe.
- If retriggered while busy: current job is cancelled, new one starts.
- Popup closes by timeout, close click, or any keypress while focused.
- Audio is written to temp file only during job and immediately deleted after transcription.

## Settings
Settings window supports:
- Hotkey
- Popup auto-hide timeout
- Launch at login toggle

Settings are stored in app config directory as `app_settings.json`.

## Logs
Local rotating logs (no telemetry):
- `app.log` (Rust app)
- `asr.log` (Python sidecar)

Both are stored under app config `logs` folder.

## Commands
Python sidecar command IPC (stdin JSON lines):
- `init`
- `start_recording`
- `stop_and_transcribe`
- `cancel_current`
- `set_config`
- `healthcheck`
- `shutdown`

Python sidecar event IPC (stdout JSON lines):
- `ready`
- `recording_started`
- `recording_stopped`
- `partial_transcript`
- `final_transcript`
- `job_cancelled`
- `error`
- `metrics`

## Tests
```bash
make test
```

## Troubleshooting
If popup shows `Model 'v3_e2e_rnnt' not found`, your sidecar was built with old GigaAM.
Rebuild sidecar and rerun debug/release build:

```bash
powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1 -Platform windows
```

If you want forced GPU sidecar build:

```bash
powershell -ExecutionPolicy Bypass -File scripts/build-sidecar.ps1 -Platform windows -Variant gpu
```

## License
This project is licensed under the MIT License. See `LICENSE`.

Third-party notice:
- GigaAM is MIT-licensed: https://github.com/salute-developers/GigaAM/blob/main/LICENSE
