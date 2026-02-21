#!/usr/bin/env python3
"""Sber Whisper ASR sidecar.

JSON lines IPC contract:
- Input commands via stdin
- Output events via stdout
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
try:
    import sounddevice as sd
except Exception as exc:  # pragma: no cover - reported at runtime
    sd = None
    SOUNDDEVICE_IMPORT_ERROR = exc
else:
    SOUNDDEVICE_IMPORT_ERROR = None

try:
    import soundfile as sf
except Exception as exc:  # pragma: no cover - reported at runtime
    sf = None
    SOUNDFILE_IMPORT_ERROR = exc
else:
    SOUNDFILE_IMPORT_ERROR = None
import torch

try:
    import gigaam
except Exception as exc:  # pragma: no cover - reported at runtime
    gigaam = None
    GIGAAM_IMPORT_ERROR = exc
else:
    GIGAAM_IMPORT_ERROR = None

SAMPLE_RATE = 16_000
CHANNELS = 1
MODEL_NAME = "v3_e2e_rnnt"
MAX_LOG_BYTES = 2 * 1024 * 1024
MIN_RECORDING_SEC = 0.35
GIGAAM_GITHUB_REF = "https://github.com/salute-developers/GigaAM"


@dataclass
class RuntimeConfig:
    language_mode: str = "ru"
    popup_timeout_sec: int = 10


@dataclass
class AppState:
    config: RuntimeConfig = field(default_factory=RuntimeConfig)
    model: Any | None = None
    model_device: str = "cpu"
    model_name_used: str = MODEL_NAME
    model_lock: threading.Lock = field(default_factory=threading.Lock)

    audio_lock: threading.Lock = field(default_factory=threading.Lock)
    stream: sd.InputStream | None = None
    frames: list[np.ndarray] = field(default_factory=list)
    recording: bool = False
    recording_started_at: float = 0.0

    transcribe_thread: threading.Thread | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    shutdown_event: threading.Event = field(default_factory=threading.Event)


def setup_logger() -> logging.Logger:
    log_dir = Path(os.environ.get("SBER_WHISPER_LOG_DIR", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("asr_sidecar")
    logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "asr.log",
        maxBytes=MAX_LOG_BYTES,
        backupCount=2,
        encoding="utf-8",
    )
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


LOGGER = setup_logger()
STATE = AppState()


def emit(event: str, **payload: Any) -> None:
    data = {"event": event, **payload}
    try:
        # Keep IPC payload ASCII-safe to avoid locale-specific stdout encodings on Windows pipes.
        sys.stdout.write(json.dumps(data, ensure_ascii=True) + "\n")
        sys.stdout.flush()
    except Exception as exc:  # pragma: no cover - io failure
        LOGGER.error("failed to emit event: %s", exc)


def choose_device() -> str:
    if sys.platform == "darwin":
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_model_if_needed() -> None:
    with STATE.model_lock:
        if STATE.model is not None:
            return

        if gigaam is None:
            raise RuntimeError(f"gigaam import failed: {GIGAAM_IMPORT_ERROR}")

        preferred = choose_device()
        LOGGER.info("loading model '%s' on %s", MODEL_NAME, preferred)

        try:
            STATE.model = gigaam.load_model(
                MODEL_NAME,
                fp16_encoder=(preferred == "cuda"),
                use_flash=False,
                device=preferred,
            )
            STATE.model_device = preferred
            STATE.model_name_used = MODEL_NAME
            LOGGER.info("loaded model '%s' on %s", MODEL_NAME, preferred)
            return
        except ValueError as exc:
            message = str(exc)
            if "Model 'v3_e2e_rnnt' not found" in message:
                raise RuntimeError(
                    "Installed gigaam package has no v3_e2e_rnnt. "
                    f"Rebuild sidecar with gigaam from {GIGAAM_GITHUB_REF}"
                ) from exc
            if preferred != "cuda":
                raise
            LOGGER.warning("failed to load model '%s' on cuda: %s", MODEL_NAME, exc)
        except Exception as exc:
            if preferred != "cuda":
                raise
            LOGGER.warning("failed to load model '%s' on cuda: %s", MODEL_NAME, exc)

        LOGGER.warning("trying CPU fallback for model '%s'", MODEL_NAME)
        try:
            STATE.model = gigaam.load_model(
                MODEL_NAME,
                fp16_encoder=False,
                use_flash=False,
                device="cpu",
            )
            STATE.model_device = "cpu"
            STATE.model_name_used = MODEL_NAME
            LOGGER.warning("loaded model '%s' with CPU fallback", MODEL_NAME)
        except Exception as exc:
            raise RuntimeError(f"Unable to load ASR model '{MODEL_NAME}': {exc}") from exc


def audio_callback(indata: np.ndarray, _frames: int, _time_info: Any, status: sd.CallbackFlags) -> None:
    if status:
        LOGGER.warning("audio callback status: %s", status)

    with STATE.audio_lock:
        if not STATE.recording:
            return
        STATE.frames.append(indata.copy())


def start_recording() -> None:
    if sd is None:
        emit("error", message=f"Audio capture dependency missing: {SOUNDDEVICE_IMPORT_ERROR}")
        return

    if STATE.recording:
        return

    cancel_current(silent=True)

    with STATE.audio_lock:
        STATE.frames = []
        STATE.recording = True
        STATE.recording_started_at = time.monotonic()

    try:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=audio_callback,
            blocksize=512,
        )
        stream.start()
        STATE.stream = stream
        emit("recording_started")
        LOGGER.info("recording started")
    except Exception as exc:
        with STATE.audio_lock:
            STATE.recording = False
            STATE.frames = []
        emit("error", message=f"Microphone error: {exc}")
        LOGGER.exception("failed to start recording")


def stop_stream_if_needed() -> list[np.ndarray]:
    with STATE.audio_lock:
        frames = STATE.frames[:]
        STATE.frames = []
        STATE.recording = False

    stream = STATE.stream
    STATE.stream = None
    if stream is not None:
        try:
            stream.stop()
            stream.close()
        except Exception:
            LOGGER.exception("failed to stop stream")

    return frames


def stop_and_transcribe() -> None:
    with STATE.audio_lock:
        started_at = STATE.recording_started_at

    elapsed = time.monotonic() - started_at if started_at > 0 else MIN_RECORDING_SEC
    if elapsed < MIN_RECORDING_SEC:
        time.sleep(MIN_RECORDING_SEC - elapsed)

    frames = stop_stream_if_needed()
    emit("recording_stopped")

    if not frames:
        emit("error", message="No audio captured. Check microphone permission or hold hotkey longer.")
        return

    STATE.cancel_event = threading.Event()

    thread = threading.Thread(target=transcribe_worker, args=(frames, STATE.cancel_event), daemon=True)
    STATE.transcribe_thread = thread
    thread.start()


def send_streaming_partials(text: str, cancel_event: threading.Event) -> None:
    words = text.split()
    if not words:
        return

    partial = []
    for word in words:
        if cancel_event.is_set():
            return
        partial.append(word)
        emit("partial_transcript", text=" ".join(partial))
        time.sleep(0.03)


def transcribe_worker(frames: list[np.ndarray], cancel_event: threading.Event) -> None:
    started_at = time.perf_counter()
    temp_path: Path | None = None

    try:
        audio = np.concatenate(frames, axis=0)
        if audio.ndim > 1:
            audio = audio[:, 0]

        if sf is None:
            raise RuntimeError(f"Audio file dependency missing: {SOUNDFILE_IMPORT_ERROR}")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            temp_path = Path(tmp.name)

        sf.write(temp_path, audio, SAMPLE_RATE)

        if cancel_event.is_set():
            emit("job_cancelled")
            return

        load_model_if_needed()

        try:
            result = STATE.model.transcribe(str(temp_path))
        except RuntimeError as exc:
            text = str(exc).lower()
            if "cuda" in text and STATE.model_device == "cuda":
                LOGGER.warning("cuda runtime failed, fallback to cpu once: %s", exc)
                with STATE.model_lock:
                    STATE.model = gigaam.load_model(
                        MODEL_NAME,
                        fp16_encoder=False,
                        use_flash=False,
                        device="cpu",
                    )
                    STATE.model_device = "cpu"
                result = STATE.model.transcribe(str(temp_path))
            else:
                raise

        if cancel_event.is_set():
            emit("job_cancelled")
            return

        if isinstance(result, dict):
            text = str(result.get("transcription", "")).strip()
        else:
            text = str(result).strip()

        send_streaming_partials(text, cancel_event)

        if cancel_event.is_set():
            emit("job_cancelled")
            return

        emit("final_transcript", text=text)

        latency_ms = int((time.perf_counter() - started_at) * 1000)
        emit(
            "metrics",
            latency_ms=latency_ms,
            device=STATE.model_device,
            model=STATE.model_name_used,
        )
        LOGGER.info("transcription done in %sms", latency_ms)
    except Exception as exc:
        emit("error", message=f"Transcription failed: {exc}")
        LOGGER.exception("transcription failed")
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                LOGGER.exception("failed to delete temp audio file")


def cancel_current(silent: bool = False) -> None:
    was_recording = STATE.recording

    if STATE.recording:
        stop_stream_if_needed()

    thread = STATE.transcribe_thread
    if thread and thread.is_alive():
        STATE.cancel_event.set()

    if (was_recording or (thread and thread.is_alive())) and not silent:
        emit("job_cancelled")


def set_config(config: dict[str, Any]) -> None:
    lang = config.get("language_mode")
    timeout_sec = config.get("popup_timeout_sec")

    if isinstance(lang, str) and lang:
        STATE.config.language_mode = lang

    if isinstance(timeout_sec, int) and timeout_sec > 0:
        STATE.config.popup_timeout_sec = timeout_sec


def healthcheck() -> None:
    emit(
        "metrics",
        device=STATE.model_device,
        model=STATE.model_name_used,
        latency_ms=0,
    )


def handle_command(cmd: dict[str, Any]) -> None:
    name = cmd.get("command")

    if name == "init":
        emit("ready", device=choose_device(), model=MODEL_NAME)
        return

    if name == "start_recording":
        start_recording()
        return

    if name == "stop_and_transcribe":
        stop_and_transcribe()
        return

    if name == "cancel_current":
        cancel_current()
        return

    if name == "set_config":
        config = cmd.get("config")
        if isinstance(config, dict):
            set_config(config)
        return

    if name == "healthcheck":
        healthcheck()
        return

    if name == "shutdown":
        cancel_current(silent=True)
        STATE.shutdown_event.set()
        return

    emit("error", message=f"Unknown command: {name}")


def run() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    LOGGER.info(
        "torch=%s torch_cuda=%s cuda_available=%s cuda_device_count=%s",
        torch.__version__,
        torch.version.cuda,
        torch.cuda.is_available(),
        torch.cuda.device_count(),
    )
    LOGGER.info("ASR sidecar started")

    for line in sys.stdin:
        if STATE.shutdown_event.is_set():
            break

        raw = line.strip()
        if not raw:
            continue

        try:
            cmd = json.loads(raw)
        except json.JSONDecodeError:
            emit("error", message="Invalid JSON command")
            continue

        if not isinstance(cmd, dict):
            emit("error", message="Command must be an object")
            continue

        handle_command(cmd)

    LOGGER.info("ASR sidecar stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
