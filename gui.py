#!/usr/bin/env python3
"""Dictate GUI — PyQt6 tray app for voice dictation via Groq Whisper."""
import math
import sys
import threading
import time

try:
    import fcntl
except ImportError:  # Windows / minimal Python: no POSIX file locking
    fcntl = None  # type: ignore[assignment]

import numpy as np
from PyQt6.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QSystemTrayIcon, QTextEdit,
    QVBoxLayout, QWidget,
)
from pynput import keyboard

import core


def _make_listener(on_press, on_release):
    """Prefer evdev (works on Wayland+Xorg); fall back to pynput on failure."""
    try:
        import evdev_listener
        l = evdev_listener.Listener(on_press=on_press, on_release=on_release)
        l.start()
        print("keyboard listener: evdev", file=sys.stderr)
        return l
    except Exception as e:
        print(f"evdev unavailable ({e}); falling back to pynput", file=sys.stderr)
        l = keyboard.Listener(on_press=on_press, on_release=on_release)
        l.daemon = True
        l.start()
        return l


# --- macOS Command double-tap poller (pynput-free) ---
#
# pynput's macOS Listener resolves the keyboard layout through HIToolbox
# (TISGetInputSourceProperty) on its worker thread. Since macOS 26 that trips
# `dispatch_assert_queue` and kills the process with SIGTRAP -- we saw this
# live on 2026-10-14 (Thread 21: Listener._run -> keycode_context ->
# TSMGetInputSourceProperty -> _dispatch_assert_queue_fail). The typing path
# is safe because it runs on the Qt main thread, but the listener thread can
# never be. So on macOS we do not use pynput's Listener at all for the
# Command double-tap hotkey: a sampler thread polls the physical key state
# instead. CGEventSourceKeyState needs no layout resolution, so HIToolbox is
# never touched off-main. (An earlier QTimer-on-main-thread attempt was
# throttled by App Nap to ~21 Hz when hidden and ate fast taps, hence the
# dedicated thread + power assertion + QoS bump below.)
try:
    if sys.platform == "darwin":
        import Quartz
        _QUARTZ_OK = hasattr(Quartz, "CGEventSourceKeyState")
    else:
        _QUARTZ_OK = False
except Exception:
    _QUARTZ_OK = False

_CMD_VKS = (55, 54)  # left / right Command (physical keycodes, layout-independent)


class _CmdTapPoller(QObject):
    """Detects Command double-taps by polling HID key state. Runs its
    sampler on a worker thread, not on a QTimer: hidden background apps get
    their runloop timers throttled (~21 Hz measured instead of 100 Hz),
    which silently eats fast taps. A sleeping sampler thread holds its
    cadence. This is crash-safe unlike pynput's listener thread because it
    never resolves keyboard layouts -- CGEventSourceKeyState needs no TSM,
    and taps reach the main thread through queued bridge signals."""

    POLL_S = 0.01
    _SCAN_VKS = tuple(vk for vk in range(128) if vk not in _CMD_VKS)

    def __init__(self, on_down, on_up, on_other):
        super().__init__()
        self._on_down = on_down
        self._on_up = on_up
        self._on_other = on_other
        self._prev_cmd = False
        self._last_beat = 0.0
        # Dictate hides itself while recording; hold a user-initiated power
        # assertion so background sampling keeps its cadence (App Nap).
        self._nap_guard = None
        try:
            from AppKit import NSProcessInfo, NSActivityUserInitiated
            self._nap_guard = NSProcessInfo.processInfo(
                ).beginActivityWithOptions_reason_(
                    NSActivityUserInitiated,
                    "Command double-tap hotkey polling")
        except Exception:
            pass
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=1.0)
        try:
            if self._nap_guard is not None:
                from AppKit import NSProcessInfo
                NSProcessInfo.processInfo().endActivity_(self._nap_guard)
                self._nap_guard = None
        except Exception:
            pass

    def _run_loop(self):
        # Background apps run their threads at background QoS, where the
        # kernel leashes wakeups to ~50 ms -- too coarse for tap detection.
        # Opt this thread out; the power assertion alone does not cover it.
        try:
            import ctypes
            import ctypes.util
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            QOS_CLASS_USER_INITIATED = 0x19
            libc.pthread_set_qos_class_self_np(QOS_CLASS_USER_INITIATED, 0)
        except Exception:
            pass
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception:
                core.log.exception("poller tick failed")
            time.sleep(self.POLL_S)

    def _tick(self):
        hid = Quartz.kCGEventSourceStateHIDSystemState
        cmd = any(Quartz.CGEventSourceKeyState(hid, vk) for vk in _CMD_VKS)
        # Quiet liveness proof in the log (one line per 5 min): distinguishes
        # "listener dead" from "no taps happened" in later debugging.
        now = time.monotonic()
        if now - self._last_beat >= 300:
            self._last_beat = now
            core.log.info("poller heartbeat (cmd hotkey active)")
        other_edge = False
        if cmd or self._prev_cmd:
            # Only scan for other keys around Command activity; idle polling
            # stays at two HID lookups per tick.
            prev = getattr(self, "_prev_other", frozenset())
            cur = frozenset(
                vk for vk in self._SCAN_VKS if Quartz.CGEventSourceKeyState(hid, vk)
            )
            other_edge = bool(cur - prev)
            self._prev_other = cur
        self.handle(cmd, other_edge)

    def handle(self, cmd_down, other_edge):
        """Pure transition logic (no Quartz here, so unit-testable headless).
        Mirrors the pynput on_press/on_release semantics for cmd_double_tap:
        press sets held, any other key while held poisons the tap, release
        resolves single vs. double tap."""
        was = self._prev_cmd
        if cmd_down and not was:
            self._on_down()
        if other_edge and (was or cmd_down):
            self._on_other()
        if was and not cmd_down:
            self._on_up()
        self._prev_cmd = cmd_down


class Bridge(QObject):
    hotkey_press = pyqtSignal()
    hotkey_release = pyqtSignal()
    hotkey_double_tap = pyqtSignal()
    other_press = pyqtSignal()
    transcribed = pyqtSignal(str)
    error = pyqtSignal(str)


class SettingsDialog(QDialog):
    # Bridge signals for the background model-download thread.
    _dl_status = pyqtSignal(str)
    _dl_done = pyqtSignal(bool, str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dictate — Settings")
        self.setMinimumWidth(460)
        self.cfg = dict(cfg)

        self.form = QFormLayout()

        # --- Provider selector ---
        self.provider_box = QComboBox()
        for pid, pdef in core.PROVIDERS.items():
            self.provider_box.addItem(pdef["label"], pid)
        i = self.provider_box.findData(self.cfg.get("provider", core.DEFAULT_PROVIDER))
        self.provider_box.setCurrentIndex(max(i, 0))
        self.provider_box.currentIndexChanged.connect(self.on_provider_changed)
        self.form.addRow("Provider:", self.provider_box)

        # --- API key row (hidden when a local provider is selected) ---
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        show_btn = QPushButton("show")
        show_btn.setCheckable(True)
        show_btn.setMaximumWidth(60)
        show_btn.toggled.connect(
            lambda on: self.api_key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.api_key_edit)
        row.addWidget(show_btn)
        self.api_key_wrap = QWidget()
        self.api_key_wrap.setLayout(row)
        self.api_key_label = QLabel()
        self.form.addRow(self.api_key_label, self.api_key_wrap)

        # --- Yorik URL row (shown only for the Yorik provider) ---
        self.yorik_url_edit = QLineEdit(self.cfg.get("yorik_url", core.DEFAULT_CONFIG["yorik_url"]))
        self.yorik_url_edit.setPlaceholderText("http://yorik.local:8000")
        self.form.addRow("Yorik URL:", self.yorik_url_edit)

        # Per-provider key cache — only providers that actually take a key.
        self._keys = {
            pid: self.cfg.get(pdef["key_field"], "")
            for pid, pdef in core.PROVIDERS.items()
            if pdef.get("key_field")
        }

        self.mode_box = QComboBox()
        self.mode_box.addItem("Push-to-talk (hold key)", "ptt")
        self.mode_box.addItem("Toggle (tap to start, tap to stop)", "toggle")
        i = self.mode_box.findData(self.cfg.get("mode", "ptt"))
        self.mode_box.setCurrentIndex(max(i, 0))
        self.form.addRow("Mode:", self.mode_box)

        self.key_box = QComboBox()
        for k in core.KEY_MAP:
            self.key_box.addItem(k.upper().replace("_", " "), k)
        i = self.key_box.findData(self.cfg.get("key", "f9"))
        self.key_box.setCurrentIndex(max(i, 0))
        self.form.addRow("Hotkey:", self.key_box)

        self.model_box = QComboBox()
        self.form.addRow("Model:", self.model_box)

        # --- Local-STT panel (shown only when a local provider is selected) ---
        import os as _os
        cpu_max = max(1, _os.cpu_count() or 1)
        self.local_status_label = QLabel()
        self.form.addRow("Local model:", self.local_status_label)
        self.local_download_btn = QPushButton()
        self.local_download_btn.clicked.connect(self.on_download_model)
        self.form.addRow("", self.local_download_btn)
        self.local_threads_box = QSpinBox()
        self.local_threads_box.setRange(1, cpu_max)
        self.local_threads_box.setValue(int(self.cfg.get("local_stt_num_threads", min(4, cpu_max))))
        self.local_threads_box.setToolTip(
            "sherpa-onnx CPU thread count. 4 = best latency/resource balance on\n"
            "this system; more brings little. Changing this rebuilds the recognizer."
        )
        self.form.addRow("CPU threads:", self.local_threads_box)

        self.threshold_box = QDoubleSpinBox()
        self.threshold_box.setRange(0.0, 5.0)
        self.threshold_box.setSingleStep(0.1)
        self.threshold_box.setDecimals(1)
        self.threshold_box.setSuffix(" s")
        self.threshold_box.setValue(float(self.cfg.get("threshold", 0.0)))
        self.threshold_box.setToolTip(
            "Recording starts immediately on press; release sends for transcription.\n"
            "If you release before this duration, the recording is discarded. 0 =\n"
            "always send. Recommended ~2.0s when bound to Ctrl/Alt/Shift so brief\n"
            "taps and shortcuts don't transcribe."
        )
        self.form.addRow("Min hold to send:", self.threshold_box)

        self.test_btn = QPushButton("Test API key")
        self.test_btn.clicked.connect(self.on_test)
        self.form.addRow("", self.test_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)

        self.hint = QLabel()
        self.hint.setOpenExternalLinks(True)
        self.hint.setStyleSheet("color: #777; padding: 6px 0;")
        layout.addWidget(self.hint)

        layout.addWidget(buttons)

        # Wire the download-worker bridge, then sync UI to current provider.
        self._dl_status.connect(self.local_status_label.setText)
        self._dl_done.connect(self._on_download_done)
        self.refresh_model_box(self.cfg.get("model", core.DEFAULT_MODEL))
        self.on_provider_changed()

    def on_provider_changed(self):
        # Persist edits to the previously-shown provider's key (if any) before
        # swapping the display to the newly selected provider.
        prev = getattr(self, "_shown_provider", None)
        if prev is not None and prev in self._keys:
            self._keys[prev] = self.api_key_edit.text().strip()

        pid = self.provider_box.currentData()
        pdef = core.PROVIDERS[pid]
        self._shown_provider = pid
        is_local = pdef.get("is_local", False)

        # HTTP-provider widgets
        if not is_local:
            self.api_key_label.setText(f"{pdef['label']} API key:")
            self.api_key_edit.setText(self._keys.get(pid, ""))
            self.api_key_edit.setPlaceholderText(f"{pdef['key_prefix']}...")

        # Toggle row visibility. QFormLayout.setRowVisible(widget, bool) hides
        # both the field and its label.
        self.form.setRowVisible(self.api_key_wrap, not is_local)
        self.form.setRowVisible(self.yorik_url_edit, pid == "yorik")
        self.form.setRowVisible(self.model_box, not is_local)
        self.form.setRowVisible(self.test_btn, not is_local)
        self.form.setRowVisible(self.local_status_label, is_local)
        self.form.setRowVisible(self.local_download_btn, is_local)
        self.form.setRowVisible(self.local_threads_box, is_local)

        # Hint text at the bottom of the dialog.
        if is_local:
            self.hint.setText(
                "Runs entirely offline on your CPU. Model: parakeet-primeline "
                "(German, ~640 MB, CC-BY-4.0). Attribution: primeline · NVIDIA · "
                "<a href='https://github.com/k2-fsa/sherpa-onnx'>k2-fsa/sherpa-onnx</a>."
            )
        elif pid == "openai":
            self.hint.setText(
                "OpenAI key: <a href='https://platform.openai.com/api-keys'>platform.openai.com/api-keys</a>."
            )
        else:
            self.hint.setText(
                "Get a free Groq API key at <a href='https://console.groq.com'>console.groq.com</a>."
            )

        self.refresh_model_box(pdef["default_model"])
        if is_local:
            self._refresh_local_status()

    def _refresh_local_status(self):
        try:
            import local_stt
            installed = local_stt.model_installed()
        except ImportError:
            self.local_status_label.setText(
                "sherpa-onnx not installed — run: pip install --user sherpa-onnx soundfile"
            )
            self.local_download_btn.setEnabled(False)
            self.local_download_btn.setText("Download model (~640 MB)")
            return
        if installed:
            self.local_status_label.setText("Installed and ready.")
            self.local_download_btn.setEnabled(True)
            self.local_download_btn.setText("Re-download model")
        else:
            self.local_status_label.setText("Not installed.")
            self.local_download_btn.setEnabled(True)
            self.local_download_btn.setText("Download model (~640 MB)")

    def on_download_model(self):
        self.local_download_btn.setEnabled(False)
        self.local_download_btn.setText("Downloading...")
        self.local_status_label.setText("Starting download...")
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _download_worker(self):
        try:
            import local_stt
            local_stt.download_model(progress_cb=lambda m: self._dl_status.emit(m))
            self._dl_done.emit(True, "Installed.")
        except Exception as e:
            self._dl_done.emit(False, f"Download failed: {e}")

    def _on_download_done(self, ok, msg):
        self.local_status_label.setText(msg)
        self.local_download_btn.setEnabled(True)
        self.local_download_btn.setText("Re-download model" if ok else "Retry download")

    def refresh_model_box(self, preferred_model):
        pid = self.provider_box.currentData()
        pdef = core.PROVIDERS[pid]
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for label, mid in pdef["models"]:
            self.model_box.addItem(label, mid)
        i = self.model_box.findData(preferred_model)
        if i < 0:
            i = self.model_box.findData(pdef["default_model"])
        self.model_box.setCurrentIndex(max(i, 0))
        self.model_box.blockSignals(False)

    def on_test(self):
        key = self.api_key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "Dictate", "Enter an API key first.")
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Testing...")
        QApplication.processEvents()
        ok = core.test_api_key(key, self.provider_box.currentData(),
                               cfg={"yorik_url": self.yorik_url_edit.text().strip()})
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Test API key")
        if ok:
            QMessageBox.information(self, "Dictate", "API key works.")
        else:
            QMessageBox.warning(self, "Dictate", "API key rejected.")

    def values(self):
        # Sync current field back into the per-provider cache first, but only
        # if the shown provider actually has a key_field (local providers don't).
        pid = self.provider_box.currentData()
        if pid in self._keys:
            self._keys[pid] = self.api_key_edit.text().strip()
        return {
            "provider":              pid,
            "api_key":               self._keys.get("groq", ""),
            "openai_api_key":        self._keys.get("openai", ""),
            "mode":                  self.mode_box.currentData(),
            "key":                   self.key_box.currentData(),
            "model":                 self.model_box.currentData(),
            "threshold":             float(self.threshold_box.value()),
            "local_stt_num_threads": int(self.local_threads_box.value()),
            "yorik_url":             self.yorik_url_edit.text().strip() or core.DEFAULT_CONFIG["yorik_url"],
            "yorik_token":           self._keys.get("yorik", ""),
        }


def make_mic_icon(color="#2b2b2b"):
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(22, 8, 20, 32, 10, 10)
    p.setPen(QColor(color))
    p.setBrush(Qt.GlobalColor.transparent)
    pen = p.pen()
    pen.setWidth(4)
    p.setPen(pen)
    p.drawArc(16, 28, 32, 24, 0, -180 * 16)
    p.drawLine(32, 50, 32, 58)
    p.drawLine(22, 58, 42, 58)
    p.end()
    return QIcon(pix)


STATUS_STYLES = {
    "ready":        ("#f3f3f3", "#222"),
    "recording":    ("#fde2e2", "#a00000"),
    "recording-quiet": ("#ffe8cc", "#9a5b00"),
    "transcribing": ("#fff3cc", "#8a6d00"),
    "error":        ("#ffd6d6", "#9a0000"),
}

#: Peak below this (of 32768) counts as silence -- same line core.py uses
#: when it reports "microphone was silent".
SILENCE_PEAK = 300


def _dbfs(peak):
    """Peak (0..32768) as dBFS, floored at -60 dB for display."""
    if peak <= 0:
        return -60.0
    return max(-60.0, 20 * math.log10(peak / 32768))


class _RecPill(QWidget):
    """Floating recording indicator. Stays on top without ever taking focus
    (tool window + show-without-activating) and joins every Space including
    fullscreen apps, so it is visible even when the user works fullscreen
    (no menu bar, no desktop) while the target app keeps keyboard focus."""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: #1c1c1e; border-radius: 12px;")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        dot = QLabel("●")
        dot.setStyleSheet(
            "color: #ff453a; font-size: 16px; background: transparent; border: none;")
        row.addWidget(dot)
        self.text = QLabel("REC")
        self.text.setStyleSheet(
            "color: white; font-size: 13px; font-weight: 600;"
            " background: transparent; border: none;")
        row.addWidget(self.text)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(110, 8)
        self.bar.setStyleSheet(
            "QProgressBar { background: #3a3a3c; border: none; border-radius: 4px; }"
            " QProgressBar::chunk { background: #30d158; border-radius: 4px; }")
        row.addWidget(self.bar)

    def show_pill(self):
        screen = QApplication.primaryScreen()
        self.adjustSize()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.top() + 24)
        self.show()
        # Plain Qt windows stay on the desktop Space and vanish under
        # fullscreen apps. Opt this one out natively: join all Spaces,
        # stay put (no Expose sliding), float as fullscreen auxiliary.
        try:
            from AppKit import (NSStatusWindowLevel,
                                NSView,
                                NSWindowCollectionBehaviorCanJoinAllSpaces,
                                NSWindowCollectionBehaviorFullScreenAuxiliary,
                                NSWindowCollectionBehaviorStationary)
            from PyQt6 import sip
            nsview = sip.wrapinstance(int(self.winId()), NSView)
            win = nsview.window()
            if win is not None:
                win.setCollectionBehavior_(
                    NSWindowCollectionBehaviorCanJoinAllSpaces
                    | NSWindowCollectionBehaviorStationary
                    | NSWindowCollectionBehaviorFullScreenAuxiliary)
                win.setLevel_(NSStatusWindowLevel)
        except Exception:
            pass


class _RecBadge:
    """Roter Aufnahme-Punkt als natives, randloses Fenster oben rechts auf dem
    Hauptbildschirm (NSScreen.screens()[0], der mit der Menueleiste), direkt
    unter der Menueleiste. Grund: macOS blendet Statusitems aus, wenn die
    Menueleiste voll ist (schmaler Hauptbildschirm); ein eigenes Fenster
    bleibt immer sichtbar. Kein Fokusklau, alle Spaces, ueber Vollbild,
    folgt Bildschirmwechseln (Sidecar an/ab). Nur Hauptthread."""

    W, H, MARGIN = 118, 26, 10

    def __init__(self):
        self._win = None
        self._label = None
        self._observer = None
        self._visible = False

    def _build(self):
        from AppKit import (NSBackingStoreBuffered, NSColor, NSFont,
                            NSMakeRect, NSPanel, NSTextField,
                            NSWindowCollectionBehaviorCanJoinAllSpaces,
                            NSWindowCollectionBehaviorFullScreenAuxiliary,
                            NSWindowCollectionBehaviorStationary)
        # borderless (0) + nonactivating panel (1 << 7)
        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, self.W, self.H), 0 | (1 << 7),
            NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        win.setIgnoresMouseEvents_(True)
        win.setHidesOnDeactivate_(False)
        win.setReleasedWhenClosed_(False)
        win.setLevel_(2002)  # ueber Menueleiste/Statusleiste (kCGScreenSaver-nah)
        win.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary)
        view = win.contentView()
        view.setWantsLayer_(True)
        layer = view.layer()
        layer.setBackgroundColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(
            0.85, 0.08, 0.08, 0.96).CGColor())
        layer.setCornerRadius_(self.H / 2)
        tf = NSTextField.labelWithString_("● REC")
        tf.setTextColor_(NSColor.whiteColor())
        tf.setFont_(NSFont.boldSystemFontOfSize_(13))
        tf.setFrame_(NSMakeRect(0, 4, self.W, 18))
        tf.setAlignment_(1)  # center
        view.addSubview_(tf)
        self._win, self._label = win, tf

    def screen(self):
        from AppKit import NSScreen
        screens = NSScreen.screens()
        return screens[0] if screens else NSScreen.mainScreen()

    def reposition(self):
        try:
            if self._win is None:
                return
            from AppKit import NSMakePoint
            f = self.screen().frame()
            vis = self.screen().visibleFrame()
            # visibleFrame.top = Unterkante der Menueleiste
            top = vis.origin.y + vis.size.height
            x = f.origin.x + f.size.width - self.W - self.MARGIN
            y = top - self.H - 4
            self._win.setFrameOrigin_(NSMakePoint(x, y))
        except Exception:
            core.log.exception("rec badge reposition failed")

    def _watch_screens(self):
        if self._observer is not None:
            return
        from AppKit import NSApplicationDidChangeScreenParametersNotification
        from Foundation import NSNotificationCenter
        self._observer = NSNotificationCenter.defaultCenter(
            ).addObserverForName_object_queue_usingBlock_(
            NSApplicationDidChangeScreenParametersNotification, None, None,
            lambda note: self.reposition())

    def show(self, text="● REC"):
        try:
            if self._win is None:
                self._build()
                self._watch_screens()
            self._label.setStringValue_(text)
            self.reposition()
            self._win.orderFrontRegardless()
            self._visible = True
            core.log.info("rec badge shown on %s", self.screen().localizedName())
        except Exception:
            core.log.exception("rec badge failed")

    def update(self, elapsed_secs, quiet):
        try:
            if self._win is None or not self._visible:
                return
            dot = "●" if int(elapsed_secs * 2) % 2 == 0 else "○"
            txt = "NO SIGNAL" if quiet else (
                f"{elapsed_secs // 60:02d}:{elapsed_secs % 60:02d}")
            self._label.setStringValue_(f"{dot} {txt}")
            self.reposition()  # billig; faengt Bildschirmwechsel mitten in der Aufnahme
        except Exception:
            pass

    def hide(self):
        try:
            if self._win is not None:
                self._win.orderOut_(None)
            self._visible = False
        except Exception:
            pass


class _RecStatusItem:
    """Permanent Dictate icon in the macOS menu bar (top right, next to the
    clock): a quiet mic dot when idle, a blinking red dot plus elapsed time
    while recording, and a NO SIGNAL warning when the mic stays silent.
    Clicking it opens the Dictate window. Native NSStatusItem, so it is
    visible no matter which app is frontmost -- unlike an in-app window,
    which hides together with Dictate. All calls must happen on the main
    thread; every method fails silently so a menu-bar hiccup can never
    break a recording."""

    def __init__(self):
        self._item = None
        self._click_target = None

    def ensure_idle(self, window):
        """Create the permanent icon once (call after startup)."""
        try:
            from AppKit import NSStatusBar, NSVariableStatusItemLength
            from Foundation import NSObject

            class _ClickForwarder(NSObject):
                def showWindow_(self, sender):
                    try:
                        if window is not None:
                            window.show_window()
                    except Exception:
                        pass

            if self._item is None:
                self._item = NSStatusBar.systemStatusBar(
                    ).statusItemWithLength_(NSVariableStatusItemLength)
                self._click_target = _ClickForwarder.alloc().init()
                self._item.button().setTarget_(self._click_target)
                self._item.button().setAction_("showWindow:")
            self.back_to_idle()
            core.log.info("menu idle icon shown")
        except Exception:
            core.log.exception("menu idle icon failed")

    def back_to_idle(self):
        try:
            if self._item is None:
                return
            from AppKit import NSColor, NSForegroundColorAttributeName
            from Foundation import NSAttributedString
            s = NSAttributedString.alloc().initWithString_attributes_(
                "◉", {NSForegroundColorAttributeName: NSColor.labelColor()})
            self._item.button().setAttributedTitle_(s)
        except Exception:
            pass

    def show(self):
        try:
            from AppKit import NSStatusBar, NSVariableStatusItemLength
            if self._item is None:
                self._item = NSStatusBar.systemStatusBar(
                    ).statusItemWithLength_(NSVariableStatusItemLength)
            self._update("● REC", False)
            core.log.info("menu indicator shown")
        except Exception:
            core.log.exception("menu indicator failed")

    def update(self, elapsed_secs, quiet):
        try:
            if self._item is None:
                return
            dot = "●" if int(elapsed_secs * 2) % 2 == 0 else "○"
            label = "NO SIGNAL" if quiet else (
                f"REC {elapsed_secs // 60:02d}:{elapsed_secs % 60:02d}")
            self._update(f"{dot} {label}", True)
        except Exception:
            pass

    def hide(self):
        self.back_to_idle()

    def _update(self, text, red):
        from AppKit import (NSColor, NSForegroundColorAttributeName,
                            NSMutableAttributedString)
        s = NSMutableAttributedString.alloc().initWithString_(text)
        dot_color = NSColor.redColor() if red else NSColor.labelColor()
        s.addAttribute_value_range_(
            NSForegroundColorAttributeName, dot_color, (0, 1))
        s.addAttribute_value_range_(
            NSForegroundColorAttributeName, NSColor.labelColor(),
            (1, max(len(text) - 1, 1)))
        self._item.button().setAttributedTitle_(s)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dictate")
        self.resize(500, 380)
        self.setWindowIcon(make_mic_icon())

        self.cfg = core.load_config()
        self.recorder = core.Recorder()
        self.bridge = Bridge()
        self.bridge.hotkey_press.connect(self.on_press)
        self.bridge.hotkey_release.connect(self.on_release)
        self.bridge.hotkey_double_tap.connect(self.on_double_tap)
        self.bridge.other_press.connect(self.on_other_press)
        self.bridge.transcribed.connect(self.on_transcribed)
        self.bridge.error.connect(self.on_error)
        self.key_held = False
        self.combo = False
        self.recording_active = False
        self.listener = None
        self._target_keys = set()
        self._last_other = None
        self._first_cmd_tap = None
        self._cmd_tap_held = False
        self._cmd_tap_interrupted = False
        self._last_dictation_app = None
        self._dictation_target = None
        self._silent_secs = 0.0
        self._warned_nosignal = False
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(100)
        self._level_timer.timeout.connect(self._update_level)
        self._recitem = _RecStatusItem()
        self._pill = _RecPill()
        self._badge = _RecBadge()
        self._rec_start = 0.0
        self._rec_wall = None

        self.press_time = 0.0

        central = QWidget()
        self.setCentralWidget(central)
        v = QVBoxLayout(central)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Dictate")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.open_settings)
        header.addWidget(self.settings_btn)
        v.addLayout(header)

        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.status_label)

        level_row = QHBoxLayout()
        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setTextVisible(False)
        self.level_bar.setMaximumHeight(10)
        level_row.addWidget(self.level_bar, stretch=1)
        self.level_label = QLabel("Level: --")
        self.level_label.setStyleSheet("color: #666;")
        level_row.addWidget(self.level_label)
        v.addLayout(level_row)

        self.info_label = QLabel()
        self.info_label.setStyleSheet("color: #666; padding: 2px 0;")
        v.addWidget(self.info_label)

        v.addWidget(QLabel("Last transcription:"))
        self.last = QTextEdit()
        self.last.setReadOnly(True)
        self.last.setMaximumHeight(110)
        self.last.setStyleSheet(
            "QTextEdit { background: #fafafa; border: 1px solid #ddd; border-radius: 6px; padding: 6px; }"
        )
        v.addWidget(self.last)

        v.addStretch()

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(make_mic_icon(), self)
            self.tray.setToolTip("Dictate")
            menu = QMenu()
            a_show = QAction("Show window", self)
            a_show.triggered.connect(self.show_window)
            a_quit = QAction("Quit", self)
            a_quit.triggered.connect(QApplication.quit)
            menu.addAction(a_show)
            menu.addSeparator()
            menu.addAction(a_quit)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self.on_tray)
            self.tray.show()

        self.set_status("ready", "Ready")
        self.update_info()
        self.start_listener()
        self._preload_local_if_needed()
        self._ensure_typing_trust()
        QTimer.singleShot(1000, lambda: self._recitem.ensure_idle(self))

        if not core.provider_key(self.cfg):
            QTimer.singleShot(250, self.first_run)

    def _ensure_typing_trust(self):
        """Typed text reaches other apps only if macOS trusts this process
        (Bedienungshilfen). Without trust, CGEventPost is silently dropped:
        transcription succeeds, but nothing arrives -- exactly the "text is
        in the app but never in the target" symptom. Terminal-started runs
        inherit trust, launchd runs do not, so check on every launch and
        raise the official system prompt when missing (self-healing, e.g.
        after a Python upgrade replaces the binary)."""
        if sys.platform != "darwin":
            return
        try:
            import ctypes
            import ctypes.util
            aslib = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
            aslib.AXIsProcessTrusted.restype = ctypes.c_bool
            if aslib.AXIsProcessTrusted():
                return
            QMessageBox.information(
                self, "Dictate",
                "Dictate darf noch nicht in andere Fenster tippen.\n\n"
                "Bitte im nächsten Dialog den Zugriff erlauben "
                "(Bedienungshilfen) -- danach landet diktierter Text "
                "im Zielfenster.")
            cf = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            k_prompt = ctypes.c_void_p.in_dll(aslib, "kAXTrustedCheckOptionPrompt")
            k_true = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
            cf.CFDictionaryCreate.restype = ctypes.c_void_p
            cf.CFDictionaryCreate.argtypes = [ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_void_p),
                                              ctypes.POINTER(ctypes.c_void_p),
                                              ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
            keys = (ctypes.c_void_p * 1)(k_prompt)
            vals = (ctypes.c_void_p * 1)(k_true)
            opts = cf.CFDictionaryCreate(None, keys, vals, 1, None, None)
            aslib.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
            aslib.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
            aslib.AXIsProcessTrustedWithOptions(opts)
        except Exception:
            pass

    def _preload_local_if_needed(self):
        """Kick off the parakeet recognizer load in the background so the first
        real dictation isn't slowed by the ~0.8s model load + warmup."""
        provider = self.cfg.get("provider")
        pdef = core.PROVIDERS.get(provider, {})
        if not pdef.get("is_local"):
            return
        try:
            import local_stt
        except ImportError:
            return
        if not local_stt.model_installed():
            return
        local_stt.preload(int(self.cfg.get("local_stt_num_threads", local_stt.DEFAULT_THREADS)))

    def first_run(self):
        QMessageBox.information(
            self,
            "Welcome to Dictate",
            "Open Settings to pick a transcription provider:\n\n"
            "  * Groq (cloud, free tier — console.groq.com)\n"
            "  * OpenAI (cloud — platform.openai.com)\n"
            "  * Local (offline, German, CPU — one-time 640 MB download)",
        )
        self.open_settings()

    def update_info(self):
        mode_name = "Push-to-talk" if self.cfg["mode"] == "ptt" else "Toggle"
        hotkey_name = (
            "COMMAND DOUBLE TAP" if self.cfg["key"] == "cmd_double_tap"
            else self.cfg["key"].upper().replace("_", " ")
        )
        thr = float(self.cfg.get("threshold", 0.0))
        thr_str = f"     Min hold: {thr:.1f}s" if thr > 0 else ""
        self.info_label.setText(
            f"Mode: {mode_name}     Hotkey: {hotkey_name}     "
            f"Model: {self.cfg['model']}{thr_str}"
        )

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.cfg.update(dlg.values())
            core.save_config(self.cfg)
            self.restart_listener()
            self.update_info()
            self._preload_local_if_needed()

    def start_listener(self):
        if (sys.platform == "darwin" and _QUARTZ_OK
                and self.cfg["key"] == "cmd_double_tap"):
            self._target_keys = set()
            print("keyboard listener: Quartz poller (sampler thread)", file=sys.stderr)
            self.listener = _CmdTapPoller(
                on_down=self._cmd_tap_down,
                on_up=self._cmd_tap_up,
                on_other=self._cmd_tap_other,
            )
            return
        keys = core.KEY_MAP.get(self.cfg["key"])
        if not keys:
            return
        self._target_keys = set(keys)

        def on_press(k):
            try:
                if k in self._target_keys:
                    if self.cfg["key"] == "cmd_double_tap":
                        self._cmd_tap_down()
                        return
                    self.bridge.hotkey_press.emit()
                else:
                    # Only a key pressed *while Command is held* turns this
                    # into a shortcut. Synthetic keystrokes from the last
                    # dictation arrive after Command was released and must
                    # not poison the following double tap.
                    if self.cfg["key"] == "cmd_double_tap":
                        self._cmd_tap_other(k)
                    else:
                        self._last_other = k
                    self.bridge.other_press.emit()
            except Exception:
                pass

        def on_release(k):
            try:
                if k in self._target_keys:
                    if self.cfg["key"] == "cmd_double_tap":
                        self._cmd_tap_up()
                        return
                    self.bridge.hotkey_release.emit()
            except Exception:
                pass

        self.listener = _make_listener(on_press, on_release)

    def _cmd_tap_down(self):
        self._cmd_tap_held = True

    def _cmd_tap_other(self, _key=None):
        if self._cmd_tap_held:
            self._cmd_tap_interrupted = True

    def _cmd_tap_up(self):
        self._cmd_tap_held = False
        now = time.monotonic()
        if self._cmd_tap_interrupted:
            self._first_cmd_tap = None
            self._cmd_tap_interrupted = False
        elif self._first_cmd_tap is not None and now - self._first_cmd_tap <= 0.45:
            self._first_cmd_tap = None
            self.bridge.hotkey_double_tap.emit()
        else:
            self._first_cmd_tap = now

    def restart_listener(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.key_held = False
        self.combo = False
        self.recording_active = False
        self._stop_level_meter()
        self.start_listener()

    def on_press(self):
        if self.key_held:
            return
        self.key_held = True
        self.combo = False
        self.press_time = time.monotonic()
        if self.cfg["mode"] == "ptt":
            if self.start_recording():
                self.recording_active = True
        else:
            if self.recording_active:
                self.stop_and_transcribe()
                self.recording_active = False
            elif self.start_recording():
                self.recording_active = True

    def on_double_tap(self):
        """Toggle recording after two clean Command-key taps on macOS."""
        if self.recording_active:
            self.stop_and_transcribe()
            self.recording_active = False
        elif self.start_recording():
            self.recording_active = True

    def on_other_press(self):
        if not self.key_held:
            return
        self.combo = True
        # Only abort if this hold started the recording (PTT). In toggle mode
        # a combo while pressing the hotkey shouldn't kill an ongoing session
        # that was started by a previous tap.
        if self.cfg["mode"] == "ptt" and self.recording_active:
            # Offload PipeWire close to keep the GUI thread responsive.
            self._discard_take()
            self.recording_active = False
            self.set_status("ready", "Cancelled (combo)")
            held = time.monotonic() - self.press_time
            core.log.info("cancelled after %.1fs by %s", held, self._last_other)
            # A shortcut like Ctrl+C cancels within a moment and needs no
            # message; a long hold was a dictation that just got thrown away.
            min_hold = float(self.cfg.get("threshold", 0.0))
            if held >= max(min_hold, 1.0):
                core.notify(f"Recording cancelled after {held:.0f}s — another key or mouse button was pressed",
                            urgency="critical", timeout_ms=5000)

    def on_release(self):
        self.key_held = False
        if self.cfg["mode"] != "ptt":
            return
        if not self.recording_active:
            return
        duration = time.monotonic() - self.press_time
        min_hold = float(self.cfg.get("threshold", 0.0))
        if min_hold > 0 and duration < min_hold:
            # Discard branch also blocks on recorder.stop() → freeze. Offload.
            self._discard_take()
            self.recording_active = False
            self.set_status("ready", f"Discarded (held {duration:.1f}s)")
            return
        self.stop_and_transcribe()
        self.recording_active = False

    def start_recording(self) -> bool:
        if not core.provider_key(self.cfg):
            self.set_status("error", "No API key — open Settings")
            return False
        try:
            self.recorder.start()
        except Exception as e:
            core.log.exception("could not open the microphone")
            self.on_error(f"Microphone: {e}")
            return False
        # Remember where the text belongs BEFORE hiding: whoever is frontmost
        # now is the dictation target. Typing later goes there even if the
        # user brought Dictate forward while waiting (its read-only pane
        # would otherwise swallow the keystrokes unnoticed). Triggered from
        # inside Dictate itself, fall back to the last target.
        target = self._frontmost_app_id()
        if target and self._is_own_app(target):
            target = self._last_dictation_app
        self._dictation_target = target
        self.set_status("recording", "Recording...")
        self._silent_secs = 0.0
        self._warned_nosignal = False
        self._rec_start = time.monotonic()
        self._rec_wall = time.strftime("%Y-%m-%d_%H-%M-%S")
        self.level_bar.setValue(0)
        self.level_label.setText("Level: --")
        self._level_timer.start()
        self._hide_for_dictation()
        self._play_sound("Pop")
        return True

    @staticmethod
    def _play_sound(name):
        try:
            from AppKit import NSSound
            sound = NSSound.soundNamed_(name)
            if sound is not None:
                sound.play()
        except Exception:
            pass

    def _hide_for_dictation(self):
        """Hide the main window; pill and menu-bar item keep recording
        visible while the dictation target keeps (or regains) focus."""
        self.hide()
        if self._dictation_target:
            self._focus_app(self._dictation_target)
        self._pill.show_pill()
        self._recitem.show()
        self._badge.show()

    def _stop_level_meter(self):
        self._level_timer.stop()
        self._pill.hide()
        self._recitem.hide()
        self._badge.hide()
        self.level_bar.setValue(0)
        self.level_label.setText("Level: --")

    def _update_level(self):
        if not self.recording_active:
            return
        try:
            peak = self.recorder.level()
        except Exception:
            return
        pct = min(int(100 * (peak / 32768) ** 0.5), 100) if peak > 0 else 0
        self.level_bar.setValue(pct)
        self._pill.bar.setValue(pct)
        elapsed = int(time.monotonic() - self._rec_start) if self._rec_start else 0
        if peak < SILENCE_PEAK:
            self._silent_secs += 0.1
            self.level_label.setText("Level: silence")
        else:
            self._silent_secs = 0.0
            self.level_label.setText(f"Level: {_dbfs(peak):.0f} dB")
        if self._silent_secs >= 3.0 and not self._warned_nosignal:
            self._warned_nosignal = True
            self.set_status("recording-quiet", "Recording... (NO SIGNAL -- check mic)")
            self._pill.text.setText("NO SIGNAL -- check mic")
            try:
                import sounddevice as _sd
                _dev = _sd.query_devices(kind="input")["name"]
            except Exception:
                _dev = "?"
            core.log.warning("recording silent for %.0fs (input device: %s)",
                             self._silent_secs, _dev)
        elif self._warned_nosignal and self._silent_secs == 0.0:
            self._warned_nosignal = False
            self.set_status("recording", "Recording...")
        if not self._warned_nosignal:
            self._pill.text.setText(f"REC {elapsed // 60:02d}:{elapsed % 60:02d}")
        self._recitem.update(elapsed, self._warned_nosignal)
        self._badge.update(elapsed, self._warned_nosignal)

    def stop_and_transcribe(self):
        # recorder.stop() can block for hundreds of ms on PipeWire close,
        # which freezes the GUI ("main on_release doesn't return"). Move the
        # whole pipeline (stop + transcribe) onto a worker thread and update
        # status immediately from the main thread instead.
        self._stop_level_meter()
        self._play_sound("Tink")
        self.set_status("transcribing", "Transcribing...")
        # Detach here, on the GUI thread: the take now belongs to the worker,
        # so pressing the hotkey again right away starts a fresh recording
        # instead of being swallowed by the worker's delayed stop.
        take = self.recorder.detach()
        threading.Thread(target=self._stop_and_transcribe_worker, args=(take,), daemon=True).start()

    def _discard_take(self):
        self._stop_level_meter()
        self._play_sound("Funk")
        take = self.recorder.detach()
        threading.Thread(target=core.Recorder.finish, args=(take,), daemon=True).start()

    def _stop_and_transcribe_worker(self, take):
        # Short trailing buffer: PipeWire has ~50-100ms input latency and
        # people typically finish the last syllable *after* they release the
        # hotkey. Without this the last word tends to get clipped.
        time.sleep(0.25)
        audio = core.Recorder.finish(take)
        if audio is None:
            core.log.warning("no audio captured (mic delivered no frames)")
            self.bridge.error.emit("No audio captured — check the microphone")
            return
        secs = len(audio) / core.SAMPLE_RATE
        peak = int(np.abs(audio).max())
        t0 = time.monotonic()
        try:
            text = core.transcribe(audio, self.cfg)
        except Exception as e:
            core.log.exception("transcribe failed: %.1fs audio, peak %d", secs, peak)
            self.bridge.error.emit(str(e))
            return
        core.log.info("transcribed %.1fs audio, peak %d, %d chars in %.1fs",
                      secs, peak, len(text or ""), time.monotonic() - t0)
        if not text:
            # Peak is out of 32768; a live mic with speech is in the thousands.
            why = "microphone was silent" if peak < 300 else "no speech recognised"
            if peak >= 300:
                core.keep_failed_audio(audio)
            self.bridge.error.emit(f"Nothing transcribed ({secs:.0f}s) — {why}")
            return
        self.bridge.transcribed.emit(text)

    def on_transcribed(self, text):
        if text:
            # On macOS pynput queries the active input source through Cocoa.
            # Cocoa asserts if that happens off the app's main (Qt) thread,
            # terminating Python with SIGTRAP after a successful transcript.
            # This slot is delivered on the Qt main thread, so type here.
            target_app = self._dictation_target or self._frontmost_app_id()
            self._dictation_target = None
            if target_app:
                self._focus_app(target_app)
            needs_space = (
                target_app is not None
                and target_app == self._last_dictation_app
                and not text[:1].isspace()
                and text[:1] not in ".,;:!?…)]}"
            )
            core.type_text((" " if needs_space else "") + text)
            self._last_dictation_app = target_app
            self.last.setPlainText(text)
            core.archive_transcript(text, when=self._rec_wall)
            self._rec_wall = None
        self.set_status("ready", "Ready")

    @staticmethod
    def _frontmost_app_id():
        """Return the macOS app currently receiving keyboard input."""
        if sys.platform != "darwin":
            return None
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            return str(app.bundleIdentifier()) if app else None
        except Exception:
            return None

    @staticmethod
    def _is_own_app(bundle_id):
        if sys.platform != "darwin":
            return False
        try:
            from AppKit import NSRunningApplication
            mine = NSRunningApplication.currentApplication().bundleIdentifier()
            return str(bundle_id) == str(mine)
        except Exception:
            return False

    @staticmethod
    def _focus_app(bundle_id):
        """Bring the dictation target forward before typing. NO-OP unless it
        is needed: if Dictate itself (or the target already) is frontmost,
        typing goes wherever the system points today, as before. Failures
        (app quit meanwhile) fall back to that same behavior."""
        if sys.platform != "darwin":
            return
        try:
            from AppKit import (NSRunningApplication,
                                NSApplicationActivateIgnoringOtherApps,
                                NSWorkspace)
            ws = NSWorkspace.sharedWorkspace()
            front = ws.frontmostApplication()
            front_id = str(front.bundleIdentifier()) if front else None
            if MainWindow._is_own_app(bundle_id) or str(bundle_id) == str(front_id):
                return
            for app in ws.runningApplications():
                if str(app.bundleIdentifier()) == str(bundle_id):
                    app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
                    time.sleep(0.35)
                    return
        except Exception:
            pass

    def on_error(self, msg):
        self.set_status("error", f"Error: {msg[:80]}")
        # The window is usually hidden in the tray, so the status label alone
        # means the dictation fails without anyone noticing.
        threading.Thread(target=core.notify, args=(msg[:200], "critical", 5000), daemon=True).start()

    def set_status(self, state, msg):
        bg, fg = STATUS_STYLES.get(state, STATUS_STYLES["ready"])
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(
            f"font-size: 24px; padding: 28px; border-radius: 10px;"
            f"background: {bg}; color: {fg};"
        )
        if self.tray:
            self.tray.setToolTip(f"Dictate — {msg}")

    def on_tray(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        QApplication.quit()


_LOCK_FD = None


def acquire_single_instance_lock():
    global _LOCK_FD
    if fcntl is None:
        return True
    core.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = core.CONFIG_DIR / "dictate.lock"
    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        core.notify("Dictate is already running", urgency="low")
        return False
    _LOCK_FD = fd
    return True


def main():
    if not acquire_single_instance_lock():
        sys.exit(0)
    core.setup_logging()
    core.log.info("started")
    # Let Ctrl+C in the terminal actually kill us — Qt's C++ event loop
    # otherwise never yields to Python's SIGINT handler.
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    app.setApplicationName("Dictate")
    has_tray = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not has_tray)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
