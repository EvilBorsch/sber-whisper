# Wispr Flow-style redesign — design

Date: 2026-08-27. Version 0.1.5 → 0.2.0.

## Goals
1. Hotkey becomes a toggle: press → start dictation, press again → stop, transcribe, and **insert text at the cursor** of the focused app (clipboard copy stays as backup).
2. Replace the big top-right Siri card with a small Wispr Flow-style pill at the bottom-center of the screen, with a live waveform driven by real microphone levels.
3. Use the latest GigaAM (main @ `7447938d`, 2026-08-17); gigaam 0.1.0 -> 0.2.0; the flagship v3 model `v3_e2e_rnnt` is unchanged — it is still the newest/best v3 model in the current registry.
4. Rebuild and update the installed `/Applications/Sber Whisper.app`.

## Approaches considered for text insertion
- **Clipboard + synthetic Cmd+V / Ctrl+V (chosen).** Standard approach of dictation apps (incl. Wispr Flow). Reliable for any text length; transcript stays in clipboard as backup. Needs macOS Accessibility permission.
- Typing text char-by-char via CGEvent unicode — slow and flaky for long texts.
- Accessibility API insertion (AXUIElement) — complex, per-app quirks. Rejected.

Raw keycodes are used (`kVK_ANSI_V`=9 on macOS, `VK_V`=0x56 on Windows) so paste works on the Russian keyboard layout. `enigo` 0.6 provides both and auto-prompts for the macOS Accessibility permission; on failure the app falls back to clipboard-only and shows a hint in the pill.

## Architecture changes
- **Rust (`lib.rs`)**
  - Global shortcut handler reacts only to `Pressed`: toggles `recording_started` → `start_recording` / `stop_and_transcribe`.
  - On `final_transcript`: copy to clipboard → short delay → synthetic paste → emit `text_inserted` (or `error` with a permission hint).
  - Popup positioned bottom-center of the current monitor; never takes focus (`focusable: false`, no `set_focus`, macOS `ActivationPolicy::Accessory` — also removes the Dock icon for this tray app).
  - Emits `dictation_starting` immediately on hotkey press so the pill appears without waiting
    for the sidecar, which can take seconds to respawn after an idle restart.
  - Dead invoke commands that no frontend calls (`start_recording`, `stop_and_transcribe`, `healthcheck`) removed; `cancel_current` is kept and now used by the pill's close button while recording.
- **Sidecar (`asr_service.py`)**
  - Emits `audio_level` (~15 Hz, RMS → 0..1) while recording to drive the waveform.
  - Fake word-by-word partial streaming removed (it only delayed the final result; the new UI shows a processing shimmer instead).
  - GigaAM pin bumped in `requirements.txt`.
- **Popup UI (`src/popup`)**
  - One small pill: listening (live waveform + red dot) → transcribing (shimmer animation) → inserted (green check, auto-hide ~1s) → error (message, auto-hide by `popup_timeout_sec`). Hover reveals close/settings buttons; close during recording cancels the job.
  - Window: 400×84 transparent, non-focusable, always-on-top, all-workspaces, no system shadow.
    Kept tight around the pill because a transparent Tauri window still swallows mouse clicks.

## Follow-up (same day, after first user feedback)
- **Transparent popup actually works now.** `transparent: true` alone renders an opaque white
  webview on macOS; the fix is `app.macOSPrivateApi: true` plus the `macos-private-api` Cargo
  feature on the `tauri` crate.
- **Settings window redesigned** to match the pill: dark panel rows (label + hint + control),
  a real toggle switch instead of a checkbox, `titleBarStyle: Overlay` + `hiddenTitle` for a
  frameless look, 460×560. `core:window:allow-start-dragging` had to be added to the capability
  because it is not part of `core:window:default`, and the hidden title bar leaves no other way
  to move the window.

## Not changed
- Settings window, tray, sidecar lifecycle/idle restart, logging, Windows build scripts (paste code is cross-platform via enigo).
- `AppSettings` schema (incl. `popup_timeout_sec` — now the error auto-hide timeout).

## Testing
- Rust unit tests (hotkey parsing, defaults) + `cargo clippy`.
- Python unittest incl. new RMS→level normalization test; `ruff` lint.
- `npm run test`, `tsc` via build.
- Manual: dev-run app, dictate into a text field, verify insertion at cursor.
