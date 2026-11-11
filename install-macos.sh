#!/bin/bash
# Kodiktat auf macOS einrichten: projektlokale .venv, Abhängigkeiten, Prüfung.
# Aufruf im Terminal aus dem Projektordner:  ./install-macos.sh
# Idempotent: kann beliebig oft laufen. Lädt kein Sprachmodell (siehe README).
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Dieser Installer ist für macOS. Unter Linux: ./install.sh" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
VENV="$SCRIPT_DIR/.venv"
PY="$VENV/bin/python"

# Gleiche Liste wie in README und install.sh; onnx-asr ist festgepinnt.
PACKAGES=(
    PyQt6 sounddevice pynput requests numpy
    sherpa-onnx soundfile huggingface_hub 'onnx-asr[cpu,hub]==0.10.2'
)

echo "Kodiktat · Installation für macOS"
echo "================================"

echo
echo "[1/4] Python-Umgebung..."
if command -v uv >/dev/null 2>&1; then
    # uv bringt bei Bedarf selbst ein passendes Python 3.11+ mit.
    uv venv --python ">=3.11" --allow-existing "$VENV"
    INSTALL=(uv pip install --python "$PY")
else
    PYTHON_BIN="$(command -v python3 || true)"
    if [[ -z "$PYTHON_BIN" ]] || ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
        echo "Python 3.11 oder neuer fehlt. Mit Homebrew: brew install python@3.12" >&2
        echo "Oder uv installieren: brew install uv" >&2
        exit 1
    fi
    [[ -x "$PY" ]] || "$PYTHON_BIN" -m venv "$VENV"
    INSTALL=("$PY" -m pip install)
fi
echo "  Umgebung: $VENV"

echo
echo "[2/4] Abhängigkeiten installieren (kann einige Minuten dauern)..."
"${INSTALL[@]}" "${PACKAGES[@]}"

echo
echo "[3/4] Prüfen, ob die Module laden..."
"$PY" - <<'PY'
import importlib
mods = ["PyQt6.QtWidgets", "sounddevice", "pynput", "requests", "numpy",
        "sherpa_onnx", "soundfile", "huggingface_hub", "onnx_asr"]
failed = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as exc:  # noqa: BLE001 - Anzeige für den Nutzer
        failed.append(f"{m}: {exc}")
if failed:
    raise SystemExit("Fehlgeschlagen:\n  " + "\n  ".join(failed))
print("  Alle Module laden.")
PY

echo
echo "[4/4] Hinweise zu macOS-Berechtigungen..."
chmod +x "$SCRIPT_DIR/install-macos.sh" 2>/dev/null || true
for f in "Dictate starten.command" "Parakeet-Modell-laden.command"; do
    [[ -f "$SCRIPT_DIR/$f" ]] && chmod +x "$SCRIPT_DIR/$f"
done

cat <<EOF

Fertig.

Nächste Schritte:
  1. Modell laden (einmalig, braucht Internet, ca. 640 MB):
       Doppelklick auf "Parakeet-Modell-laden.command"
       (für Primeline statt v3 im Terminal: zsh "Parakeet-Modell-laden.command" de)
  2. Kodiktat starten:
       Doppelklick auf "Dictate starten.command"
  3. Beim ersten Start in den Systemeinstellungen erlauben:
       - Datenschutz & Sicherheit > Mikrofon
       - Datenschutz & Sicherheit > Bedienungshilfen (Text in andere Fenster tippen)
       - Datenschutz & Sicherheit > Eingabeüberwachung (falls macOS danach fragt;
         die Command-Taste zweimal tippen liest den Tastenstatus)
     Danach Kodiktat neu starten.

Wichtig: Die Rechte hängen am genauen Pfad der Python-Datei:
  $(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$PY")
Ändert sich der Pfad (uv-/brew-Update, .venv neu gebaut), fehlen Bedienungshilfen
wieder: Aufnahme und Erkennung laufen, aber es wird nichts getippt. Kodiktat warnt
dann beim Start im Log (typing NOT trusted) und öffnet die Einstellungen.
EOF
