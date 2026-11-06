"""Offline regressions; synthetic arrays only, no model download required."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import local_stt as stt


def ready_rec(language="auto", backend=None):
    rec = object.__new__(stt.LocalRecognizer)
    rec.language = language
    rec.model_info = stt.model_info(language)
    rec.num_threads = 4
    rec._recognizer = backend or Mock()
    rec._decode_lock = threading.Lock()
    rec._ready = threading.Event()
    rec._ready.set()
    rec._load_error = None
    return rec


class SelectionTests(unittest.TestCase):
    def test_default_and_english_are_multilingual(self):
        for mode in ("auto", "en"):
            info = stt.model_info(mode)
            self.assertEqual(info["repo_id"], stt.MULTILINGUAL_REPO)
            self.assertEqual(info["provider"], "CPUExecutionProvider")
            self.assertFalse(info["language_forced"])
            json.dumps(info)
        self.assertEqual(stt.model_info("de")["repo_id"], stt.MODEL_REPO)

    def test_invalid_modes_and_threads_fail_before_loading(self):
        for mode in ("fr", "EN", "", None):
            for function in (stt.model_info, stt.model_installed, stt.get_recognizer, stt.preload):
                with self.assertRaises(ValueError):
                    function(language=mode)
            with self.assertRaises(ValueError):
                stt.download_model(language=mode)
        for count in (0, -1, 4.0, True):
            with self.assertRaises(ValueError):
                stt.get_recognizer(count)

    def test_singleton_tracks_mode_threads_and_model(self):
        with patch.object(stt, "_instance", None), patch.object(stt, "LocalRecognizer") as cls:
            cls.side_effect = lambda n, language: SimpleNamespace(
                num_threads=n, model_info=stt.model_info(language))
            a = stt.get_recognizer(4)
            self.assertIs(stt.preload(4), a)
            en = stt.get_recognizer(4, "en")
            self.assertIsNot(en, a)
            de = stt.get_recognizer(4, "de")
            self.assertIsNot(de, en)
            self.assertIsNot(stt.get_recognizer(2, "de"), de)
            with patch.object(stt, "MODEL_REVISION", "other-revision"):
                self.assertEqual(stt.get_recognizer(2, "de").model_info["revision"], "other-revision")


class InstallationTests(unittest.TestCase):
    def test_models_are_checked_separately_and_empty_files_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stt, "MODEL_DIR", Path(tmp)/"de"), patch.object(stt, "MULTILINGUAL_DIR", Path(tmp)/"v3"):
            root = Path(stt.model_info("de")["model_dir"])
            root.mkdir()
            for name in stt.MODEL_FILES:
                (root/name).write_bytes(b"synthetic")
            self.assertTrue(stt.model_installed("de"))
            self.assertFalse(stt.model_installed())
            (root/stt.MODEL_FILES[0]).write_bytes(b"")
            self.assertFalse(stt.model_installed("de"))

    def test_download_pins_revision_and_reports_incomplete_or_network_error(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(stt, "MULTILINGUAL_DIR", Path(tmp)), patch("huggingface_hub.snapshot_download") as dl:
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                stt.download_model(None, "en")  # existing positional callback preserved
            self.assertEqual(dl.call_args.kwargs["revision"], stt.MULTILINGUAL_REVISION)
            self.assertEqual(dl.call_args.kwargs["allow_patterns"], stt.MULTILINGUAL_FILES)
            dl.side_effect = OSError("synthetic offline failure")
            with self.assertRaisesRegex(RuntimeError, "synthetic offline failure"):
                stt.download_model(language="auto")

    def test_missing_model_never_loads_or_downloads_another(self):
        with patch.object(stt, "model_installed", return_value=False), patch("onnx_asr.load_model") as load, patch("huggingface_hub.snapshot_download") as dl:
            rec = stt.LocalRecognizer(4, "auto")
            self.assertTrue(rec.wait_ready(5))
            self.assertFalse(rec.is_ready())
            with self.assertRaisesRegex(RuntimeError, "parakeet-tdt-0.6b-v3-int8.*missing/incomplete"):
                rec.transcribe(np.zeros(16000, dtype=np.int16))
            load.assert_not_called()
            dl.assert_not_called()

    def test_multilingual_loader_is_local_cpu_and_load_failure_is_visible(self):
        backend = Mock()
        backend.recognize.return_value = ""
        with patch.object(stt, "model_installed", return_value=True), patch("onnx_asr.load_model", return_value=backend) as load:
            rec = stt.LocalRecognizer(3, "en")
            self.assertTrue(rec.wait_ready(5))
            self.assertTrue(rec.is_ready())
            args, kwargs = load.call_args
            self.assertEqual(args, ("nemo-conformer-tdt", stt.MULTILINGUAL_DIR))
            self.assertEqual(kwargs["providers"], ["CPUExecutionProvider"])
            self.assertEqual(kwargs["sess_options"].intra_op_num_threads, 3)
            self.assertEqual(kwargs["quantization"], "int8")
        with patch.object(stt, "model_installed", return_value=True), patch("onnx_asr.load_model", side_effect=RuntimeError("synthetic damaged ONNX")):
            rec = stt.LocalRecognizer(4)
            rec.wait_ready(5)
            with self.assertRaisesRegex(RuntimeError, "synthetic damaged ONNX"):
                rec.transcribe(np.zeros(16000, dtype=np.int16))


class DecodeTests(unittest.TestCase):
    def test_empty_and_silence_do_not_hallucinate(self):
        rec = ready_rec()
        for audio in (np.array([], dtype=np.int16), np.zeros((16000, 1), dtype=np.int16)):
            self.assertEqual(rec.transcribe(audio), "")
            self.assertEqual(rec.transcribe_with_timestamps(audio)["tokens"], [])
        rec._recognizer.recognize.assert_not_called()

    def test_invalid_audio_fails_and_float64_is_not_rescaled(self):
        for audio in (np.zeros((100, 2)), np.array([np.nan]), np.array([np.inf]), np.array([2.0]), np.array([1], dtype=np.uint8)):
            with self.assertRaises(ValueError):
                ready_rec().transcribe(audio)
        np.testing.assert_array_equal(stt._prepare_audio(np.array([.5], dtype=np.float64)), [.5])
        self.assertEqual(stt._prepare_audio(np.array([16384], dtype=np.int16))[0], .5)

    def test_chunking_keeps_every_sample_and_gain_is_bounded(self):
        audio = np.full(61*stt.TARGET_SR, .001, dtype=np.float32)
        chunks = list(stt._split(audio, 25))
        self.assertGreater(len(chunks), 2)
        self.assertLessEqual(max(map(len, chunks)), 25*stt.TARGET_SR)
        np.testing.assert_array_equal(np.concatenate(chunks), audio)
        self.assertAlmostEqual(float(stt._raise_gain(audio).max()), .03, places=5)
        rec = ready_rec()
        rec._recognizer.recognize.return_value = "synthetic"
        self.assertEqual(rec.transcribe(audio), " ".join(["synthetic"]*len(chunks)))
        for call in rec._recognizer.recognize.call_args_list:
            self.assertLessEqual(len(call.args[0]), 25*stt.TARGET_SR)

    def test_empty_long_decode_retries_shorter_chunks(self):
        rec = ready_rec("de")
        rec._decode = Mock(side_effect=["", "first", "last"])
        self.assertEqual(rec.transcribe(np.full(30*stt.TARGET_SR, .1, np.float32)), "first last")

    def test_timestamps_use_global_offsets_for_chunks_and_retry(self):
        rec = ready_rec()
        audio = np.full(40*stt.TARGET_SR, .1, np.float32)
        audio[int(23.7*stt.TARGET_SR):int(24.5*stt.TARGET_SR)] = .001
        rec._decode_timed = lambda c: {"text": "test", "tokens": ["▁test"], "timestamps": [.2], "duration": len(c)/stt.TARGET_SR}
        result = rec.transcribe_with_timestamps(audio)
        self.assertEqual(len(result["tokens"]), 2)
        first = len(next(stt._split(audio, 25))) / stt.TARGET_SR
        self.assertAlmostEqual(result["timestamps"][1], first+.2)
        rec._decode_timed = lambda c: {"text": "" if len(c)>20*stt.TARGET_SR else "test", "tokens": [] if len(c)>20*stt.TARGET_SR else ["▁test"], "timestamps": [] if len(c)>20*stt.TARGET_SR else [.2], "duration": len(c)/stt.TARGET_SR}
        result = rec.transcribe_with_timestamps(audio)
        self.assertEqual(len(result["tokens"]), 3)
        self.assertGreater(result["timestamps"][-1], 20)


if __name__ == "__main__":
    unittest.main()
