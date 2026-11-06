"""Local CPU STT: multilingual Parakeet v3 (auto/en), Primeline (de).

Offline transducer. Loads once at first use, warmed up so subsequent decodes
have consistent latency. Not thread-safe over a single recognizer instance —
we serialize decode calls with a lock; for single-user dictation that's fine.
"""
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np

MODEL_DIR = Path.home() / ".local" / "share" / "dictate" / "models" / "parakeet-primeline-onnx"
MODEL_REPO = "flozen1981/parakeet-primeline-onnx"
# Pin the revision so users always get the exact bits we tested against.
MODEL_REVISION = "d548e25b9bfe559aa274f361892dc4ed5d64743a"
MODEL_FILES = [
    "encoder.int8.onnx",
    "encoder.int8.onnx.data",   # the 621 MB weight blob — MUST be next to encoder.int8.onnx
    "decoder.int8.onnx",
    "joiner.int8.onnx",
    "tokens.txt",
]
TARGET_SR = 16000
DEFAULT_THREADS = 4
LANGUAGES = ("auto", "de", "en")
MULTILINGUAL_DIR = MODEL_DIR.parent / "parakeet-tdt-0.6b-v3-onnx"
MULTILINGUAL_REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
MULTILINGUAL_REVISION = "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce"
MULTILINGUAL_FILES = [
    "config.json", "encoder-model.int8.onnx", "decoder_joint-model.int8.onnx", "vocab.txt",
]
TARGET_PEAK = 0.5   # quiet pieces are raised to this peak before decoding
MAX_GAIN = 30.0     # but never amplified more than this, so room noise stays noise


def model_info(language: str = "auto") -> dict:
    """Return JSON-safe selection metadata, without loading/downloading a model.

    language is a requested mode, not detected speech language. en selects v3;
    v3 detects languages automatically and has no language-forcing switch.
    MODEL_* constants remain Primeline aliases for older external callers.
    """
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported local STT language {language!r}; choose auto, de or en")
    german = language == "de"
    return {
        "language": language,
        "model_id": "parakeet-primeline-int8" if german else "parakeet-tdt-0.6b-v3-int8",
        "repo_id": MODEL_REPO if german else MULTILINGUAL_REPO,
        "revision": MODEL_REVISION if german else MULTILINGUAL_REVISION,
        "model_dir": str(MODEL_DIR if german else MULTILINGUAL_DIR),
        "files": list(MODEL_FILES if german else MULTILINGUAL_FILES),
        "backend": "sherpa-onnx" if german else "onnx-asr",
        "provider": "CPUExecutionProvider",
        "automatic_language_detection": not german,
        "language_forced": False,
    }


def model_installed(language: str = "auto") -> bool:
    info = model_info(language)
    root = Path(info["model_dir"])
    return all((root / f).is_file() and (root / f).stat().st_size > 0 for f in info["files"])


def download_model(progress_cb: Optional[Callable[[str], None]] = None, language: str = "auto") -> None:
    """Download the selected pinned model revision from Hugging Face.

    Blocks. Raises RuntimeError on failure. `progress_cb(msg)` gets short
    status strings for GUI display.
    """
    info = model_info(language)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise RuntimeError(
            "huggingface_hub is not installed — run: pip install huggingface_hub"
        ) from e
    root = Path(info["model_dir"])
    root.mkdir(parents=True, exist_ok=True)
    if progress_cb:
        progress_cb(f"Downloading {info['model_id']} (~640 MB, one-time) ...")
    try:
        snapshot_download(
            repo_id=info["repo_id"], revision=info["revision"],
            local_dir=str(root), allow_patterns=info["files"],
        )
        if not model_installed(language):
            raise RuntimeError("Model files are incomplete or empty")
    except Exception as e:
        raise RuntimeError(f"Download failed for {info['model_id']}: {e}") from e
    if progress_cb:
        progress_cb("Model downloaded.")


class LocalRecognizer:
    """CPU recognizer with async load, warmup and serialized decoding."""

    def __init__(self, num_threads: int, language: str = "auto"):
        self.model_info = model_info(language)
        if not isinstance(num_threads, int) or isinstance(num_threads, bool) or num_threads < 1:
            raise ValueError("num_threads must be a positive integer")
        self.language = language
        self.num_threads = num_threads
        self._recognizer = None
        self._decode_lock = threading.Lock()
        self._ready = threading.Event()
        self._load_error: Optional[Exception] = None
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            if not model_installed(self.language):
                raise FileNotFoundError(
                    f"{self.model_info['model_id']} missing/incomplete in {self.model_info['model_dir']}; "
                    f"run download_model(language={self.language!r}) explicitly"
                )
            root = Path(self.model_info["model_dir"])
            if self.language == "de":
                import sherpa_onnx
                rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=str(root / "encoder.int8.onnx"),
                    decoder=str(root / "decoder.int8.onnx"),
                    joiner=str(root / "joiner.int8.onnx"),
                    tokens=str(root / "tokens.txt"),
                    model_type="nemo_transducer", provider="cpu",
                    num_threads=self.num_threads, decoding_method="greedy_search",
                )
            else:
                import onnx_asr
                import onnxruntime as ort
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = self.num_threads
                opts.inter_op_num_threads = 1
                # Architecture name + existing local path: no Hub resolution,
                # implicit download, CoreML, CUDA or network fallback.
                rec = onnx_asr.load_model(
                    "nemo-conformer-tdt", root, quantization="int8",
                    providers=["CPUExecutionProvider"], sess_options=opts,
                )
            # Warmup: two 1-second silences. First real decode is ~2x slower
            # without this, and the user is waiting on the first one.
            for _ in range(2):
                silence = np.zeros(TARGET_SR, dtype=np.float32)
                if self.language == "de":
                    s = rec.create_stream()
                    s.accept_waveform(TARGET_SR, silence)
                    rec.decode_stream(s)
                else:
                    rec.recognize(silence, sample_rate=TARGET_SR)
            self._recognizer = rec
        except Exception as e:
            self._load_error = e
        finally:
            self._ready.set()

    def is_ready(self) -> bool:
        return self._ready.is_set() and self._recognizer is not None

    def wait_ready(self, timeout: Optional[float] = None) -> bool:
        return self._ready.wait(timeout)

    def transcribe(self, audio: np.ndarray) -> str:
        """Take int16 mono 16 kHz audio (shape (N,) or (N, 1)), return text."""
        self._ready.wait()
        if self._recognizer is None:
            raise RuntimeError(f"{self.model_info['model_id']} ({self.language}) failed to load: {self._load_error}") from self._load_error
        audio = _prepare_audio(audio)
        parts = []
        with self._decode_lock:
            for chunk in _split(audio, MAX_CHUNK_S if self.language == "de" else MULTILINGUAL_CHUNK_S):
                text = self._decode(chunk)
                # The model now and then returns nothing for a long piece that
                # clearly holds speech; shorter pieces of the same audio decode.
                if not text and len(chunk) > RETRY_CHUNK_S * TARGET_SR:
                    text = " ".join(t for t in map(self._decode, _split(chunk, RETRY_CHUNK_S)) if t)
                parts.append(text)
        return " ".join(p for p in parts if p)

    def transcribe_with_timestamps(self, audio: np.ndarray) -> dict:
        """Return text + token start times (seconds), not word/end times.

        Uses the same model, chunking and gain as transcribe. SentencePiece
        tokens (runtime output: leading spaces) need grouping by the consuming
        word-time tool. They are not complete words or word end times.
        """
        self._ready.wait()
        if self._recognizer is None:
            raise RuntimeError(f"{self.model_info['model_id']} ({self.language}) failed to load: {self._load_error}") from self._load_error
        audio = _prepare_audio(audio)
        result = {"text": "", "tokens": [], "timestamps": [], "model_info": dict(self.model_info)}
        texts, offset = [], 0.0
        with self._decode_lock:
            for chunk in _split(audio, MAX_CHUNK_S if self.language == "de" else MULTILINGUAL_CHUNK_S):
                res = self._decode_timed(chunk)
                pieces = [res]
                if not res["text"] and len(chunk) > RETRY_CHUNK_S * TARGET_SR:
                    pieces = [self._decode_timed(c) for c in _split(chunk, RETRY_CHUNK_S)]
                local_offset = offset
                for res in pieces:
                    texts.append(res["text"])
                    result["tokens"].extend(res["tokens"])
                    result["timestamps"].extend(local_offset + t for t in res["timestamps"])
                    local_offset += res["duration"]
                offset += len(chunk) / TARGET_SR
        result["text"] = " ".join(t for t in texts if t)
        return result

    def _decode_timed(self, chunk: np.ndarray) -> dict:
        duration = len(chunk) / TARGET_SR
        if not len(chunk) or not np.any(chunk):
            return {"text": "", "tokens": [], "timestamps": [], "duration": duration}
        chunk = _raise_gain(chunk)
        if self.language == "de":
            s = self._recognizer.create_stream()
            s.accept_waveform(TARGET_SR, chunk)
            self._recognizer.decode_stream(s)
            res = s.result
        else:
            res = self._recognizer.with_timestamps().recognize(chunk, sample_rate=TARGET_SR)
        return {"text": res.text.strip(), "tokens": list(res.tokens),
                "timestamps": list(res.timestamps), "duration": duration}

    def _decode(self, chunk: np.ndarray) -> str:
        # Quiet input (speech around -45 dBFS, peak ~0.03) comes back empty
        # as a whole; the same audio raised to a peak of 0.5 decodes in full.
        if not len(chunk) or not np.any(chunk):
            return ""
        chunk = _raise_gain(chunk)
        if self.language != "de":
            return self._recognizer.recognize(chunk, sample_rate=TARGET_SR).strip()
        s = self._recognizer.create_stream()
        s.accept_waveform(TARGET_SR, chunk)
        self._recognizer.decode_stream(s)
        return s.result.text.strip()


# The encoder fails outright on more than 400 s of audio ("Attempting to
# broadcast an axis ...") and its memory grows quadratically before that
# (180 s ≈ 3.5 GB), so long dictations are decoded in pieces.
MAX_CHUNK_S = 90
MULTILINGUAL_CHUNK_S = 25  # onnx-asr recommends 20–30 s; avoid quadratic encoder memory
RETRY_CHUNK_S = 20  # piece length for the second pass over a piece that came back empty
_SEARCH_S = 15      # look for a pause in the last part of each piece
_WIN_S = 0.4


def _prepare_audio(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio)
    if audio.ndim == 2 and audio.shape[1] == 1:
        audio = audio[:, 0]
    if audio.ndim != 1:
        raise ValueError("Expected mono 16 kHz audio with shape (N,) or (N, 1)")
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0
    elif np.issubdtype(audio.dtype, np.floating):
        audio = audio.astype(np.float32)
    else:
        raise ValueError("Expected int16 PCM or floating point audio in [-1, 1]")
    if not np.isfinite(audio).all() or (len(audio) and np.abs(audio).max() > 1.0):
        raise ValueError("Audio must be finite and within [-1, 1]")
    return np.ascontiguousarray(audio)


def _raise_gain(chunk: np.ndarray) -> np.ndarray:
    peak = float(np.abs(chunk).max()) if len(chunk) else 0.0
    if 0.0 < peak < TARGET_PEAK:
        return chunk * min(TARGET_PEAK / peak, MAX_GAIN)
    return chunk


def _split(audio: np.ndarray, max_s: float = MAX_CHUNK_S):
    """Yield pieces of at most max_s, cut at the quietest spot near the end."""
    search_s = min(_SEARCH_S, max_s / 2)
    max_n, search_n, win_n = (int(x * TARGET_SR) for x in (max_s, search_s, _WIN_S))
    while len(audio) > max_n:
        tail = audio[max_n - search_n:max_n]
        n_win = len(tail) // win_n
        energy = (tail[:n_win * win_n].reshape(n_win, win_n) ** 2).mean(axis=1)
        cut = max_n - search_n + int(energy.argmin()) * win_n + win_n // 2
        yield audio[:cut]
        audio = audio[cut:]
    yield audio


_instance: Optional[LocalRecognizer] = None
_instance_lock = threading.Lock()


def get_recognizer(num_threads: int = DEFAULT_THREADS, language: str = "auto") -> LocalRecognizer:
    """Get or (re)create the process-wide singleton.

    A thread-count, language or model change builds a fresh recognizer.
    """
    global _instance
    info = model_info(language)
    if not isinstance(num_threads, int) or isinstance(num_threads, bool) or num_threads < 1:
        raise ValueError("num_threads must be a positive integer")
    with _instance_lock:
        if (_instance is None or _instance.num_threads != num_threads
                or _instance.model_info != info):
            _instance = LocalRecognizer(num_threads, language)
        return _instance


def preload(num_threads: int = DEFAULT_THREADS, language: str = "auto") -> LocalRecognizer:
    """Kick off the model load in the background so the first real decode is fast."""
    return get_recognizer(num_threads, language)
