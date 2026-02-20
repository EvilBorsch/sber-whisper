from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[2] / "python" / "asr_service.py"
spec = importlib.util.spec_from_file_location("asr_service", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("failed to load asr_service module")

asr_service = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = asr_service
spec.loader.exec_module(asr_service)


class SidecarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[dict] = []
        self._old_emit = asr_service.emit
        asr_service.emit = lambda event, **payload: self.events.append({"event": event, **payload})

    def tearDown(self) -> None:
        asr_service.emit = self._old_emit

    def test_set_config_updates_runtime(self) -> None:
        asr_service.handle_command({"command": "set_config", "config": {"language_mode": "ru", "popup_timeout_sec": 22}})
        self.assertEqual(asr_service.STATE.config.language_mode, "ru")
        self.assertEqual(asr_service.STATE.config.popup_timeout_sec, 22)

    def test_unknown_command_emits_error(self) -> None:
        asr_service.handle_command({"command": "unknown"})
        self.assertTrue(any(e["event"] == "error" for e in self.events))


if __name__ == "__main__":
    unittest.main()
