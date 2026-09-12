# Sber Whisper Desktop

Cross-platform desktop voice-to-text app (Windows + macOS) with:
- Tray/top-bar background mode
- Global toggle hotkey (`Ctrl+G` on Windows, `Cmd+G` on macOS): press to start dictation, press again to stop
- Final text is inserted at the cursor of the focused app (and kept in the clipboard as backup)
- Compact Wispr Flow-style pill at the bottom of the screen with a live microphone waveform
- Dictations of any length: audio is split on pauses into chunks the model accepts (GigaAM takes at most 25 s per call)
- Filler words are stripped from the result: hesitations (`э`, `эм`, `мм`, `а-а`, `м-м`) and words like `ну`, `типа`, `как бы`, `короче`, `вот`; punctuation and sentence capitalization are repaired
- Local-only processing with GigaAM `v3_e2e_rnnt`
- Bundled Python sidecar in installer (target machine does not need Python)

On macOS the app needs two permissions: Microphone and Accessibility (for inserting text
via synthetic `Cmd+V`). The Accessibility prompt appears on the first insertion; until it
is granted, text is only copied to the clipboard.

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
- App starts hidden in tray/top-bar and preloads the ASR model in the background.
- Press global hotkey to start recording; press again to stop, transcribe and insert text at the cursor.
- If the model is not in memory yet (first run, or after the keepalive timeout), the pill shows
  `Loading model…` while the model loads; the waveform appears as soon as the model is ready.
  After a keepalive unload the microphone already records during the load, so nothing said is lost.
  Only a cold start of the sidecar process (app launch, or after a crash) delays recording until the
  process is up, which is why the app preloads the model right after launch.
- Long dictations are cut into chunks of up to 20 s at the quietest moment of the last 8 s of each window,
  each chunk is transcribed separately and the texts are joined.
- The joined text is cleaned from filler words before insertion (the list lives in `FILLER_PHRASES`
  and `HESITATION_RE` in `python/asr_service.py`). A dictation that consisted only of fillers inserts nothing.
- When the model is idle longer than the keepalive timeout it is unloaded from memory, but the sidecar
  process stays alive: restarting Python with torch takes seconds, reloading the model takes about one.
- The pill popup never takes keyboard focus, so the target app keeps the cursor.
- Pill hides itself after insertion; errors hide by `popup_timeout_sec` or close click.
- Audio is written to temp file only during job and immediately deleted after transcription.

## Settings
Settings window supports:
- Hotkey
- Popup auto-hide timeout (applies to error messages; success hides automatically)
- Model keepalive timeout (minutes before ASR model unloads from RAM/VRAM when idle)
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
- `audio_level`
- `recording_stopped`
- `model_loading`
- `model_loaded`
- `final_transcript`
- `job_cancelled`
- `error`
- `metrics`

The Rust shell additionally emits `dictation_starting` (right on hotkey press, before the
sidecar answers), `model_loading` (when it has to start the sidecar process) and `text_inserted`
(after a successful paste) to the popup.

## Tests
```bash
make test
```

`make test` runs the frontend (vitest), Python sidecar (unittest) and Rust (cargo test) suites.
Python sidecar tests need `torch`, `gigaam`, `soundfile` and `numpy`; `make test` uses `python/.venv-sidecar`
(created by the sidecar build) when it exists.

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
