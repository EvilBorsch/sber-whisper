from __future__ import annotations

import importlib.util
import sys
import threading
import time
import unittest
from collections.abc import Callable
from pathlib import Path

import numpy as np
import soundfile as sf

MODULE_PATH = Path(__file__).resolve().parents[2] / "python" / "asr_service.py"
spec = importlib.util.spec_from_file_location("asr_service", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("failed to load asr_service module")

asr_service = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = asr_service
spec.loader.exec_module(asr_service)

SR = asr_service.SAMPLE_RATE
MODEL_LIMIT_SEC = 25.0


class FakeResult:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeModel:
    """Модель-заглушка: как настоящая GigaAM, отказывается от записей длиннее 25 секунд."""

    def __init__(self) -> None:
        self.chunk_durations: list[float] = []
        self.on_transcribe: Callable[[], None] = lambda: None

    def transcribe(self, wav_path: str) -> FakeResult:
        self.on_transcribe()
        audio, sr = sf.read(wav_path, dtype="float32")
        duration = len(audio) / sr
        if duration > MODEL_LIMIT_SEC:
            raise ValueError("Too long wav file, use 'transcribe_longform' method.")
        self.chunk_durations.append(duration)
        return FakeResult(f"chunk{len(self.chunk_durations)}")


class FakeStream:
    def __init__(self, **_kwargs) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


def speech_with_pauses(total_sec: float, pause_every_sec: float, pause_sec: float) -> np.ndarray:
    """Синтетическая «речь»: шум с периодическими паузами тишины."""
    rng = np.random.default_rng(0)
    audio = rng.uniform(-0.3, 0.3, int(total_sec * SR)).astype(np.float32)
    period = int(pause_every_sec * SR)
    pause = int(pause_sec * SR)
    for start in range(period, len(audio), period):
        audio[start : start + pause] = 0.0
    return audio


class SidecarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[dict] = []
        self._old_emit = asr_service.emit
        asr_service.emit = lambda event, **payload: self.events.append({"event": event, **payload})
        asr_service.STATE = asr_service.AppState()
        self.fake_model = FakeModel()
        self._old_load_model = asr_service.gigaam.load_model
        asr_service.gigaam.load_model = lambda *_args, **_kwargs: self.fake_model
        self._old_stream = asr_service.sd.InputStream
        asr_service.sd.InputStream = FakeStream

    def tearDown(self) -> None:
        asr_service.cancel_current(silent=True)
        asr_service.emit = self._old_emit
        asr_service.gigaam.load_model = self._old_load_model
        asr_service.sd.InputStream = self._old_stream

    def event_names(self) -> list[str]:
        return [e["event"] for e in self.events if e["event"] != "audio_level"]

    def wait_for_event(self, name: str, timeout_sec: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_sec
        while name not in self.event_names():
            if time.monotonic() > deadline:
                self.fail(f"event '{name}' was not emitted, got {self.event_names()}")
            time.sleep(0.01)

    def test_set_config_updates_runtime(self) -> None:
        asr_service.handle_command({"command": "set_config", "config": {"language_mode": "ru", "popup_timeout_sec": 22}})
        self.assertEqual(asr_service.STATE.config.language_mode, "ru")
        self.assertEqual(asr_service.STATE.config.popup_timeout_sec, 22)

    def test_unknown_command_emits_error(self) -> None:
        asr_service.handle_command({"command": "unknown"})
        self.assertTrue(any(e["event"] == "error" for e in self.events))

    def test_rms_to_level_normalization(self) -> None:
        self.assertEqual(asr_service.rms_to_level(0.0), 0.0)
        self.assertAlmostEqual(asr_service.rms_to_level(0.01), 0.3, places=3)
        self.assertEqual(asr_service.rms_to_level(0.5), 1.0)

    def test_long_dictation_is_transcribed_in_chunks_within_model_limit(self) -> None:
        asr_service.STATE.model = self.fake_model
        audio = speech_with_pauses(total_sec=70.0, pause_every_sec=7.0, pause_sec=0.5)
        frames = [audio[i : i + 512] for i in range(0, len(audio), 512)]

        asr_service.transcribe_worker(frames, threading.Event())

        final = [e for e in self.events if e["event"] == "final_transcript"]
        self.assertEqual(len(final), 1, self.events)
        self.assertEqual(final[0]["text"], " ".join(f"chunk{i + 1}" for i in range(len(self.fake_model.chunk_durations))))
        self.assertGreater(len(self.fake_model.chunk_durations), 1)
        self.assertTrue(all(d <= MODEL_LIMIT_SEC for d in self.fake_model.chunk_durations))
        self.assertAlmostEqual(sum(self.fake_model.chunk_durations), 70.0, places=2)
        self.assertNotIn("error", self.event_names())

    def test_short_dictation_is_a_single_chunk(self) -> None:
        asr_service.STATE.model = self.fake_model
        audio = speech_with_pauses(total_sec=4.0, pause_every_sec=1.0, pause_sec=0.2)

        asr_service.transcribe_worker([audio], threading.Event())

        self.assertEqual(self.fake_model.chunk_durations, [4.0])
        self.assertEqual([e["text"] for e in self.events if e["event"] == "final_transcript"], ["chunk1"])

    def test_chunks_are_cut_on_quietest_moment(self) -> None:
        audio = speech_with_pauses(total_sec=30.0, pause_every_sec=18.0, pause_sec=1.0)

        chunks = asr_service.split_audio(audio, SR)

        self.assertEqual(len(chunks), 2)
        # Разрез попадает внутрь паузы 18.0–19.0 с, а не в середину слова.
        self.assertTrue(18.0 * SR <= len(chunks[0]) <= 19.0 * SR, len(chunks[0]) / SR)

    def test_recording_slightly_longer_than_chunk_keeps_tail_in_previous_chunk(self) -> None:
        audio = speech_with_pauses(total_sec=20.3, pause_every_sec=19.95, pause_sec=0.1)

        chunks = asr_service.split_audio(audio, SR)

        # Хвост в пару сотен миллисекунд модель не распознает — он приклеивается к предыдущему куску.
        self.assertEqual([len(c) for c in chunks], [len(audio)])

    def test_cancel_while_model_is_busy_drops_result(self) -> None:
        asr_service.STATE.model = self.fake_model
        cancel_event = threading.Event()
        self.fake_model.on_transcribe = cancel_event.set

        asr_service.transcribe_worker([speech_with_pauses(3.0, 1.0, 0.1)], cancel_event)

        self.assertEqual(self.event_names(), ["job_cancelled"])

    def test_start_recording_captures_audio_while_model_loads(self) -> None:
        asr_service.handle_command({"command": "start_recording"})

        # Запись стартует сразу, модель догружается фоном — начало фразы не теряется.
        self.assertTrue(asr_service.STATE.recording)
        self.assertEqual(self.event_names()[:2], ["model_loading", "recording_started"])
        self.wait_for_event("model_loaded")
        self.assertEqual(self.event_names(), ["model_loading", "recording_started", "model_loaded"])
        self.assertIs(asr_service.STATE.model, self.fake_model)

    def test_start_recording_with_loaded_model_does_not_report_loading(self) -> None:
        asr_service.STATE.model = self.fake_model
        asr_service.handle_command({"command": "start_recording"})
        time.sleep(0.05)
        self.assertNotIn("model_loading", self.event_names())

    def test_init_preloads_model(self) -> None:
        asr_service.handle_command({"command": "init"})

        self.assertEqual(self.event_names()[:2], ["ready", "model_loading"])
        self.wait_for_event("model_loaded")
        self.assertIs(asr_service.STATE.model, self.fake_model)

    def test_idle_timeout_unloads_model_but_keeps_sidecar_alive(self) -> None:
        asr_service.STATE.model = self.fake_model
        asr_service.STATE.config.model_keepalive_min = 5
        asr_service.STATE.model_last_used_at = time.monotonic() - 6 * 60

        asr_service.unload_model_if_idle(time.monotonic())

        self.assertIsNone(asr_service.STATE.model)
        self.assertNotIn("sidecar_idle_restart", self.event_names())

    def test_model_reloads_after_idle_unload_on_next_dictation(self) -> None:
        asr_service.STATE.model = self.fake_model
        asr_service.STATE.model_last_used_at = time.monotonic() - 60 * 60
        asr_service.unload_model_if_idle(time.monotonic())

        asr_service.handle_command({"command": "start_recording"})
        self.wait_for_event("model_loaded")
        asr_service.STATE.frames = [speech_with_pauses(2.0, 1.0, 0.1)]
        asr_service.handle_command({"command": "stop_and_transcribe"})
        self.wait_for_event("final_transcript")

        self.assertEqual(self.fake_model.chunk_durations, [2.0])


if __name__ == "__main__":
    unittest.main()
