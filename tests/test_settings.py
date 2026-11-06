"""Settings/routing regression tests without microphone, hotkey or network."""
import json
import os
os.environ.setdefault("PYNPUT_BACKEND", "dummy")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
import core
import local_stt


class ConfigTests(unittest.TestCase):
    def test_new_and_legacy_config_selection(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(core, "CONFIG_PATH", Path(tmp)/"config.json"):
            self.assertEqual(core.load_config()["local_stt_language"], "auto")
            core.CONFIG_PATH.write_text(json.dumps({"provider": "parakeet_local", "model": "parakeet-primeline-int8", "key": "f10"}))
            cfg = core.load_config()
            self.assertEqual(core.local_language(cfg), "de")
            self.assertEqual(cfg["key"], "f10")
            core.CONFIG_PATH.write_text(json.dumps({"provider": "openai", "model": "whisper-1"}))
            self.assertEqual(core.load_config()["provider"], "openai")
        self.assertEqual(core.local_language({"model": "parakeet-primeline-int8", "local_stt_language": "auto"}), "auto")
        with self.assertRaises(ValueError):
            core.local_language({"local_stt_language": "invalid"})

    def test_core_routes_selected_mode_and_propagates_errors_without_http(self):
        audio = np.zeros(16000, dtype=np.int16)
        for language in ("auto", "de", "en"):
            cfg = {"provider": "parakeet_local", "local_stt_language": language, "local_stt_num_threads": 2}
            with patch.object(local_stt, "get_recognizer") as get, patch.object(core.requests, "post") as post:
                get.return_value.transcribe.return_value = "synthetic"
                self.assertEqual(core.transcribe(audio, cfg), "synthetic")
                get.assert_called_once_with(num_threads=2, language=language)
                get.return_value.transcribe.side_effect = RuntimeError("synthetic CPU error")
                with self.assertRaisesRegex(RuntimeError, "synthetic CPU error"):
                    core.transcribe(audio, cfg)
                post.assert_not_called()
            with patch.object(local_stt, "model_installed", return_value=True) as installed:
                self.assertTrue(core.provider_key(cfg))
                installed.assert_called_once_with(language)


class SettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_gui_roundtrip_and_preload_use_selected_mode(self):
        import gui
        for language in ("auto", "de", "en"):
            cfg = dict(core.DEFAULT_CONFIG, provider="parakeet_local", local_stt_language=language, key="f10")
            with patch.object(local_stt, "model_installed", return_value=True):
                dlg = gui.SettingsDialog(cfg)
                values = dlg.values()
                self.assertEqual(values["local_stt_language"], language)
                self.assertEqual(values["model"], local_stt.model_info(language)["model_id"])
                self.assertEqual(values["key"], "f10")
                dlg.close()
            fake_window = Mock(cfg=cfg)
            with patch.object(local_stt, "model_installed", return_value=True), patch.object(local_stt, "preload") as preload:
                gui.MainWindow._preload_local_if_needed(fake_window)
                preload.assert_called_once_with(4, language=language)

    def test_download_worker_captures_selected_language(self):
        import gui
        dlg = gui.SettingsDialog(dict(core.DEFAULT_CONFIG, provider="parakeet_local"))
        with patch.object(local_stt, "download_model") as download:
            dlg._download_worker("en")
            self.assertEqual(download.call_args.kwargs["language"], "en")
        dlg.close()


if __name__ == "__main__":
    unittest.main()
