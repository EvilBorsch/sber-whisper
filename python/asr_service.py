#!/usr/bin/env python3
"""Сервис распознавания речи Sber Whisper.

Протокол IPC в формате JSON Lines:
- команды поступают через stdin;
- события отправляются через stdout.
"""

from __future__ import annotations
import gc
import json
import logging
import logging.handlers
import math
import os
import re
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
except Exception as exc:  # pragma: no cover — ошибка сообщается во время выполнения
    sd = None
    SOUNDDEVICE_IMPORT_ERROR = exc
else:
    SOUNDDEVICE_IMPORT_ERROR = None

try:
    import soundfile as sf
except Exception as exc:  # pragma: no cover — ошибка сообщается во время выполнения
    sf = None
    SOUNDFILE_IMPORT_ERROR = exc
else:
    SOUNDFILE_IMPORT_ERROR = None
import torch

if sys.platform == "darwin":
    os.environ["PATH"] = f"/opt/homebrew/bin:/usr/local/bin:{os.environ.get('PATH', '')}"

try:
    import gigaam
except Exception as exc:  # pragma: no cover — ошибка сообщается во время выполнения
    gigaam = None
    GIGAAM_IMPORT_ERROR = exc
else:
    GIGAAM_IMPORT_ERROR = None

SAMPLE_RATE = 16_000
CHANNELS = 1
MODEL_NAME = "v3_e2e_rnnt"
MAX_LOG_BYTES = 2 * 1024 * 1024
MIN_RECORDING_SEC = 0.35
# Модель принимает не больше 25 с, поэтому длинные записи режем на куски с запасом.
CHUNK_MAX_SEC = 20.0
CHUNK_CUT_SEARCH_SEC = 8.0
CHUNK_CUT_FRAME_SEC = 0.02
LEVEL_EMIT_INTERVAL_SEC = 0.066
# Заминки вроде «э», «эм», «мм», «хм», «а-а», «м-м». Одиночные «а», «у», «м» не трогаем:
# это союз, предлог и метры.
HESITATION_RE = re.compile(r"^(?:э+м*|м{2,}|хм+|[эмау]+(?:-[эмау]+)+)$")
FILLER_PHRASES = ("ну", "типа", "как бы", "короче", "вот", "в общем", "это самое", "так сказать", "блин")
WORD_PUNCT = ".,!?;:…«»\"()-—–"
SENTENCE_END = ".!?…"
GIGAAM_GITHUB_REF = "https://github.com/salute-developers/GigaAM"


@dataclass
class RuntimeConfig:
    language_mode: str = "ru"
    popup_timeout_sec: int = 10
    model_keepalive_min: int = 5


@dataclass
class AppState:
    config: RuntimeConfig = field(default_factory=RuntimeConfig)
    model: Any | None = None
    model_device: str = "cpu"
    model_name_used: str = MODEL_NAME
    model_last_used_at: float = 0.0
    transcribing: bool = False
    model_lock: threading.Lock = field(default_factory=threading.Lock)

    audio_lock: threading.Lock = field(default_factory=threading.Lock)
    stream: sd.InputStream | None = None
    frames: list[np.ndarray] = field(default_factory=list)
    recording: bool = False
    recording_started_at: float = 0.0
    level: float = 0.0

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
        # ASCII-совместимый JSON не зависит от кодировки stdout в каналах Windows.
        sys.stdout.write(json.dumps(data, ensure_ascii=True) + "\n")
        sys.stdout.flush()
    except Exception as exc:  # pragma: no cover — ошибка ввода-вывода
        LOGGER.error("failed to emit event: %s", exc)


def choose_device() -> str:
    if sys.platform == "darwin":
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_model_if_needed() -> None:
    with STATE.model_lock:
        if STATE.model is not None:
            STATE.model_last_used_at = time.monotonic()
            return

        if gigaam is None:
            raise RuntimeError(f"gigaam import failed: {GIGAAM_IMPORT_ERROR}")

        preferred = choose_device()
        LOGGER.info("loading model '%s' on %s", MODEL_NAME, preferred)
        started_at = time.perf_counter()

        try:
            STATE.model = gigaam.load_model(
                MODEL_NAME,
                fp16_encoder=(preferred == "cuda"),
                use_flash=False,
                device=preferred,
            )
            STATE.model_device = preferred
            STATE.model_name_used = MODEL_NAME
            STATE.model_last_used_at = time.monotonic()
            LOGGER.info("loaded model '%s' on %s in %.1fs", MODEL_NAME, preferred, time.perf_counter() - started_at)
            emit("model_loaded", device=preferred)
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
            STATE.model_last_used_at = time.monotonic()
            LOGGER.warning("loaded model '%s' with CPU fallback", MODEL_NAME)
            emit("model_loaded", device="cpu")
        except Exception as exc:
            raise RuntimeError(f"Unable to load ASR model '{MODEL_NAME}': {exc}") from exc


def preload_model_in_background() -> None:
    """Греет модель, не блокируя запись: ошибку покажет распознавание, когда модель понадобится."""
    if STATE.model is not None:
        return

    emit("model_loading")

    def worker() -> None:
        try:
            load_model_if_needed()
        except Exception:
            LOGGER.exception("background model load failed")

    threading.Thread(target=worker, daemon=True).start()


def touch_model_last_used() -> None:
    with STATE.model_lock:
        if STATE.model is not None:
            STATE.model_last_used_at = time.monotonic()


def set_transcribing(active: bool) -> None:
    with STATE.model_lock:
        STATE.transcribing = active
        if active and STATE.model is not None:
            STATE.model_last_used_at = time.monotonic()


def unload_model_if_idle(now: float) -> None:
    with STATE.model_lock:
        keepalive_min = STATE.config.model_keepalive_min
        keepalive_sec = max(1, keepalive_min) * 60

        if STATE.model is None or STATE.transcribing or STATE.model_last_used_at <= 0:
            return

        idle_sec = now - STATE.model_last_used_at
        if idle_sec < keepalive_sec:
            return

        # Процесс с импортированным torch остаётся жить: его холодный старт занимает
        # секунды и терял начало диктовки, а сама модель перегружается быстро.
        STATE.model = None
        STATE.model_last_used_at = 0.0

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    LOGGER.info("idle timeout reached after %.1fs (keepalive=%s min), model unloaded", idle_sec, keepalive_min)


def model_idle_reaper() -> None:
    while not STATE.shutdown_event.wait(timeout=5.0):
        unload_model_if_idle(time.monotonic())


def rms_to_level(rms: float) -> float:
    # Корень сглаживает динамику: тихая речь заметна, громкая не упирается в потолок.
    return round(min(1.0, math.sqrt(max(0.0, rms)) * 3.0), 3)


def audio_callback(indata: np.ndarray, _frames: int, _time_info: Any, status: sd.CallbackFlags) -> None:
    if status:
        LOGGER.warning("audio callback status: %s", status)

    with STATE.audio_lock:
        if not STATE.recording:
            return
        STATE.frames.append(indata.copy())
        STATE.level = rms_to_level(float(np.sqrt(np.mean(np.square(indata)))))


def level_emitter() -> None:
    while STATE.recording:
        with STATE.audio_lock:
            level = STATE.level
        emit("audio_level", level=level)
        time.sleep(LEVEL_EMIT_INTERVAL_SEC)


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
        STATE.level = 0.0

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
        preload_model_in_background()
        emit("recording_started")
        threading.Thread(target=level_emitter, daemon=True).start()
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
        emit("error", message="No audio captured. Check microphone permission.")
        return

    STATE.cancel_event = threading.Event()

    thread = threading.Thread(target=transcribe_worker, args=(frames, STATE.cancel_event), daemon=True)
    STATE.transcribe_thread = thread
    thread.start()


def split_audio(audio: np.ndarray, sample_rate: int) -> list[np.ndarray]:
    """Режет запись на куски не длиннее CHUNK_MAX_SEC.

    Разрез ставится в самом тихом 20-мс кадре последних CHUNK_CUT_SEARCH_SEC секунд окна,
    чтобы не резать слово посередине.
    """
    max_len = int(CHUNK_MAX_SEC * sample_rate)
    search_len = int(CHUNK_CUT_SEARCH_SEC * sample_rate)
    frame_len = int(CHUNK_CUT_FRAME_SEC * sample_rate)

    chunks: list[np.ndarray] = []
    start = 0
    while len(audio) - start > max_len:
        search_start = start + max_len - search_len
        frames = audio[search_start : start + max_len].reshape(-1, frame_len)
        quietest = int(np.argmin(np.mean(np.square(frames), axis=1)))
        cut = search_start + quietest * frame_len + frame_len // 2
        chunks.append(audio[start:cut])
        start = cut

    # Хвост короче минимальной записи модель не распознает — приклеиваем к предыдущему куску.
    tail = audio[start:]
    if chunks and len(tail) < MIN_RECORDING_SEC * sample_rate:
        chunks[-1] = np.concatenate([chunks[-1], tail])
    else:
        chunks.append(tail)
    return chunks


def transcribe_audio(audio: np.ndarray, cancel_event: threading.Event) -> str | None:
    """Распознаёт запись любой длины по кускам; None — если задачу отменили."""
    texts: list[str] = []
    for chunk in split_audio(audio, SAMPLE_RATE):
        if cancel_event.is_set():
            return None

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            temp_path = Path(tmp.name)
        try:
            sf.write(temp_path, chunk, SAMPLE_RATE)
            text = STATE.model.transcribe(str(temp_path)).text.strip()
        finally:
            temp_path.unlink(missing_ok=True)

        if text:
            texts.append(text)

    if cancel_event.is_set():
        return None
    return clean_transcript(" ".join(texts))


def clean_transcript(text: str) -> str:
    """Убирает заминки и слова-паразиты, сохраняя пунктуацию и заглавные буквы предложений.

    Текст режется на токены «слово + знаки». Точка или вопрос с удалённого токена переезжает
    на предыдущее оставленное слово, запятая просто выбрасывается.
    """
    fillers = sorted((phrase.split() for phrase in FILLER_PHRASES), key=len, reverse=True)
    tokens = text.split()
    words = [token.strip(WORD_PUNCT).lower() for token in tokens]

    kept: list[str] = []
    capitalize_next = False
    i = 0
    while i < len(tokens):
        span = 0
        if HESITATION_RE.match(words[i]):
            span = 1
        else:
            for phrase in fillers:
                crosses_sentence = any(token[-1] in SENTENCE_END for token in tokens[i : i + len(phrase) - 1])
                if words[i : i + len(phrase)] == phrase and not crosses_sentence:
                    span = len(phrase)
                    break

        if span == 0:
            token = tokens[i]
            if capitalize_next:
                token = token[:1].upper() + token[1:]
                capitalize_next = False
            kept.append(token)
            i += 1
            continue

        # Удалили начало предложения — заглавную букву получит следующее оставленное слово.
        if not kept or kept[-1][-1] in SENTENCE_END:
            capitalize_next = True

        last = tokens[i + span - 1]
        sentence_end = [c for c in last[len(last.rstrip(WORD_PUNCT)) :] if c in SENTENCE_END]
        if sentence_end and kept and kept[-1][-1] not in SENTENCE_END:
            kept[-1] = kept[-1].rstrip(",;:") + sentence_end[0]
        i += span

    return " ".join(kept)


def transcribe_worker(frames: list[np.ndarray], cancel_event: threading.Event) -> None:
    started_at = time.perf_counter()
    set_transcribing(True)

    try:
        audio = np.concatenate(frames, axis=0)
        if audio.ndim > 1:
            audio = audio[:, 0]

        if sf is None:
            raise RuntimeError(f"Audio file dependency missing: {SOUNDFILE_IMPORT_ERROR}")

        load_model_if_needed()
        touch_model_last_used()

        try:
            text = transcribe_audio(audio, cancel_event)
        except RuntimeError as exc:
            if "cuda" not in str(exc).lower() or STATE.model_device != "cuda":
                raise
            LOGGER.warning("cuda runtime failed, fallback to cpu once: %s", exc)
            with STATE.model_lock:
                STATE.model = gigaam.load_model(
                    MODEL_NAME,
                    fp16_encoder=False,
                    use_flash=False,
                    device="cpu",
                )
                STATE.model_device = "cpu"
                STATE.model_last_used_at = time.monotonic()
            text = transcribe_audio(audio, cancel_event)

        touch_model_last_used()

        if text is None:
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
        LOGGER.info("transcription of %.1fs audio done in %sms", len(audio) / SAMPLE_RATE, latency_ms)
    except Exception as exc:
        emit("error", message=f"Transcription failed: {exc}")
        LOGGER.exception("transcription failed")
    finally:
        set_transcribing(False)


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
    keepalive_min = config.get("model_keepalive_min")

    if isinstance(lang, str) and lang:
        STATE.config.language_mode = lang

    if isinstance(timeout_sec, int) and timeout_sec > 0:
        STATE.config.popup_timeout_sec = timeout_sec

    if isinstance(keepalive_min, int) and 1 <= keepalive_min <= 240:
        STATE.config.model_keepalive_min = keepalive_min


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
        preload_model_in_background()
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
    threading.Thread(target=model_idle_reaper, daemon=True).start()
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
