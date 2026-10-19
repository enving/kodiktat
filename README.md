<h1 align="center">Kodiktat</h1>

<p align="center"><strong>Diktieren per Hotkey. Auf Deutsch. Lokal. Open Source.</strong></p>

<p align="center">
  <a href="LICENSE"><img alt="Lizenz: MIT" src="https://img.shields.io/badge/Lizenz-MIT-6c3ce1"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776ab">
  <img alt="Spracherkennung: NVIDIA Parakeet" src="https://img.shields.io/badge/ASR-NVIDIA%20Parakeet-76b900">
  <img alt="Läuft lokal" src="https://img.shields.io/badge/l%C3%A4uft-lokal-0e8f7e">
  <img alt="Plattformen: macOS, Linux, Windows" src="https://img.shields.io/badge/macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-lightgrey">
</p>

<p align="center">
  <a href="#-schnellstart">Schnellstart</a> ·
  <a href="#-funktionen">Funktionen</a> ·
  <a href="#-bedienung">Bedienung</a> ·
  <a href="#-fehlersuche">Fehlersuche</a> ·
  <a href="#-die-ko-familie">Ko-Familie</a> ·
  <a href="#-herkunft-und-lizenz">Herkunft</a>
</p>

---

> **Kurz gesagt: Taste halten oder zweimal antippen, sprechen, loslassen – der Text erscheint dort, wo dein Cursor steht.**

**Kodiktat** verwandelt gesprochene Sprache in getippten Text, in jedem Programm: Editor, Terminal,
Browser, Chat. Mit dem lokalen Modell **Parakeet** (Deutsch) bleibt dein Audio auf dem eigenen
Rechner – ohne Konto, ohne Abo, ohne Internet. Wer will, schaltet stattdessen Groq, OpenAI oder
einen eigenen Server (Yorik) ein.

## 💡 Warum dieses Projekt?

Diktierfunktionen in Betriebssystemen und Cloud-Diensten sind bequem, schicken aber jedes Wort an
fremde Server oder erkennen Deutsch nur mittelmäßig. Kodiktat dreht das um:

| | Kodiktat | typische Cloud-Diktierdienste |
|---|---|---|
| Wo landet das Audio? | **auf deinem Rechner** (lokaler Modus) | Server des Anbieters |
| Deutsch | **deutsch feinabgestimmtes Modell** | oft nachrangig |
| Kosten | **kostenlos**, Open Source (MIT) | Abo oder Kontingent |
| Offline nutzbar | **ja**, nach dem einmaligen Modell-Download | nein |
| Wohin kommt der Text? | **in jedes Programm**, an den Cursor | meist nur in die eigene App |

## ✨ Funktionen

<table>
<tr>
<td width="50%" valign="top">

**🎙️ Aufnehmen**
- Push-to-talk (halten) oder Umschalten (antippen)
- Hotkey: Funktionstaste, Ctrl/Alt/Shift/Super, Maus-Seitentaste – auf dem Mac **Command zweimal antippen**
- Mindest-Haltedauer gegen versehentliche Tastendrücke
- Pegelanzeige und Warnung bei stummem Mikrofon

**👀 Sehen, dass es läuft**
- **Rotes Abzeichen** unter der Menüleiste (macOS): „● REC“, Laufzeit, bei Stille „NO SIGNAL“
- Symbol in der Menüleiste, Signalton beim Start und Stopp
- Statussymbol im Systemabschnitt (Linux)

</td>
<td width="50%" valign="top">

**🧠 Erkennen**
- **Lokal**: `parakeet-primeline` (deutsches Feintuning von NVIDIA Parakeet, int8-ONNX über [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)), nur CPU, ca. 50 ms für 2 s Sprache
- **Yorik** (Heimserver): ein Parakeet für alle Geräte im Haus
- **Groq**: `whisper-large-v3-turbo`, `whisper-large-v3`
- **OpenAI**: `gpt-4o-mini-transcribe`, `gpt-4o-transcribe`, `whisper-1`

**🛟 Nichts geht verloren**
- Lange Aufnahmen werden an Pausen zerlegt
- Fehlgeschlagene Aufnahmen bleiben als WAV erhalten (die letzten 3)
- Jede Aufnahme wird als Textdatei archiviert

</td>
</tr>
</table>

## 🚀 Schnellstart

### macOS

```bash
git clone https://github.com/enving/kodiktat.git
cd kodiktat
python3 -m venv .venv
./.venv/bin/pip install PyQt6 sounddevice pynput requests numpy sherpa-onnx soundfile huggingface_hub
```

Danach `./.venv/bin/python gui.py` starten oder **`Dictate starten.command`** doppelklicken.
Für Diktat ganz ohne Internet: **`Parakeet-Modell-laden.command`** doppelklicken. Das Skript lädt das
Modell (ca. 640 MB, fortsetzbar, mit Prüfsumme) und stellt Kodiktat auf den lokalen Anbieter und
Command-Doppeltipp um. Einmal neu starten, fertig.

Beim ersten Start fragt macOS nach **Bedienungshilfen** (damit Text in andere Fenster getippt werden
darf) und nach dem **Mikrofon**. Beides erlauben, sonst kommt zwar Text an, aber nicht im Zielfenster.

### Linux

```bash
git clone https://github.com/enving/kodiktat.git
cd kodiktat
./install.sh
```

Der Installer richtet Systempakete (`xdotool`, `ydotool`, `python3-evdev`, `libportaudio2` u. a.),
Python-Pakete, die Gruppe `input` (für evdev unter Wayland) und einen Menüeintrag ein. Danach einmal
ab- und anmelden. Das Parakeet-Modell lädst du bei Bedarf in den Einstellungen herunter.
Hintergründe zu Wayland: [WAYLAND_NOTES.md](WAYLAND_NOTES.md).

### Windows

```bash
pip install PyQt6 sounddevice pynput requests numpy
python gui.py
```

### Als Dienst auf dem Mac (optional)

Wer Kodiktat beim Anmelden automatisch starten will, legt einen LaunchAgent an
(`~/Library/LaunchAgents/…plist` mit `RunAtLoad` und `KeepAlive`, Programm
`<Ordner>/.venv/bin/python <Ordner>/gui.py`) und lädt ihn mit `launchctl bootstrap gui/$(id -u) <plist>`.

## 🎛️ Bedienung

Standard-Hotkey unter Linux/Windows ist **F9**, auf dem Mac **Command zweimal antippen**
(Umschaltmodus). Sprechen, nochmal tippen – der Text steht am Cursor.

- **Rotes Abzeichen**: Solange aufgenommen wird, zeigt ein rotes Fenster oben rechts unter der
  Menüleiste des Hauptbildschirms „● REC“ mit Laufzeit. Es nimmt keinen Fokus, erscheint auf allen
  Arbeitsflächen und über Vollbildprogrammen. Bleibt das Mikrofon länger als 3 Sekunden stumm,
  steht dort **NO SIGNAL**.
- **Einstellungen**: Anbieter, Modus (halten/umschalten), Hotkey, Modell, CPU-Threads (lokal; 4 passt
  meist), Mindest-Haltedauer (ca. 2 s, wenn eine Modifikatortaste als Hotkey dient).
- **Konfiguration**: `~/.config/dictate/config.json` (Rechte 600), Schlüssel bleiben lokal.
- **Headless**: `dictate.py` ist die schlanke Kommandozeilenvariante für X11
  (`export GROQ_API_KEY=…; python3 dictate.py --mode ptt --key f9`).

```json
{
  "provider": "parakeet_local",
  "mode": "toggle",
  "key": "f9",
  "threshold": 0.0,
  "local_stt_num_threads": 4
}
```

Gültige Anbieter: `groq`, `openai`, `yorik`, `parakeet_local`.

## 🔍 Fehlersuche

Jede Aufnahme hinterlässt eine Zeile in `~/.local/state/dictate/dictate.log` (Länge, Pegel,
Zeichenzahl, Dauer – nie der Text), inklusive dem benutzten **Eingabegerät**.

- **Abzeichen zeigt „NO SIGNAL“ / Pegel immer 0**: Das Mikrofon liefert reine Stille. Meist ist das
  Gerät selbst die Ursache (Funkmikrofon aus, stummgeschaltet oder außer Reichweite, falsches
  Standard-Eingabegerät). Im Log steht, welches Gerät benutzt wurde; in den Systemeinstellungen unter
  Ton → Eingabe ein anderes wählen.
- **Text erscheint, aber nicht im Zielfenster**: macOS: Bedienungshilfen prüfen. Linux: `ydotool`
  und `/dev/uinput`.
- **Hotkey tut nichts (Linux)**: `groups | grep input` im selben Terminal; im Start-Log muss
  `keyboard listener: evdev` stehen.
- **Aufnahme ohne Text**: Hatte sie Ton, liegt sie als WAV in `~/.local/state/dictate/failed/`
  (nur dein Ordner, nichts wird hochgeladen, jederzeit löschbar).

## 🧬 Die Ko-Familie

Kodiktat gehört zu einer kleinen Familie lokaler, deutscher Open-Source-Werkzeuge mit der Vorsilbe
**Ko** (wie *Kollege*, *kooperativ*, *Kontext*): [**Koprotokoll**](https://github.com/enving/Koprotokoll)
schreibt Meetings mit, **Kodiktat** diktiert, weitere Werkzeuge teilen sich dasselbe deutsche
Spracherkennungsmodell.

## 🤝 Herkunft und Lizenz

Kodiktat ist ein **Fork von [winidi/dictate](https://github.com/winidi/dictate)** (MIT) und baut auf
dessen Aufnahme-, Hotkey- und Anbieterlogik auf. Dazu kamen die macOS-Fassung (Quartz-Hotkey, Tipp-
Freigabe, Pegelanzeige, Menüleistensymbol, rotes Abzeichen, Archiv je Aufnahme) und die deutsche
Ausrichtung. Der Upstream bleibt als Git-Remote `upstream` eingebunden.

Modelle und Laufzeit (CC-BY-4.0 bzw. ihre eigenen Lizenzen):
[primeline](https://huggingface.co/flozen1981/parakeet-primeline-onnx) (Feintuning),
[NVIDIA](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) (Basismodell),
[k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (Laufzeit).

**Lizenz: MIT** – siehe [LICENSE](LICENSE). Der ursprüngliche Urheberhinweis (winidi, 2026) bleibt
erhalten.
