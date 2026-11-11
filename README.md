<h1 align="center">Kodiktat</h1>

<p align="center"><strong>Diktieren per Hotkey. Deutsch und Englisch. Lokal. Open Source.</strong></p>

<p align="center">
  <a href="LICENSE"><img alt="Lizenz: MIT" src="https://img.shields.io/badge/Lizenz-MIT-6c3ce1"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776ab">
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
Browser, Chat. Mit dem lokalen Modell **Parakeet v3** bleibt dein deutsches oder englisches Audio auf dem eigenen
Rechner – ohne Konto, ohne Abo, ohne Internet. Wer will, schaltet stattdessen Groq, OpenAI oder
einen eigenen Server (Yorik) ein.

## 💡 Warum dieses Projekt?

Diktierfunktionen in Betriebssystemen und Cloud-Diensten sind bequem, schicken aber jedes Wort an
fremde Server oder erkennen Deutsch nur mittelmäßig. Kodiktat dreht das um:

| | Kodiktat | typische Cloud-Diktierdienste |
|---|---|---|
| Wo landet das Audio? | **auf deinem Rechner** (lokaler Modus) | Server des Anbieters |
| Sprachen | **automatische Erkennung, u. a. Deutsch und Englisch; Primeline für Deutsch wählbar** | abhängig vom Anbieter |
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
- **Lokal, Standard `auto`**: NVIDIA Parakeet TDT 0.6B v3, mehrsprachig mit automatischer Spracherkennung, int8-ONNX über [onnx-asr](https://github.com/istupakov/onnx-asr), ausdrücklich CPU
- **Lokal, `de`**: `parakeet-primeline`, deutsch spezialisiertes Feintuning, int8-ONNX über [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), CPU
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
./install-macos.sh
```

Der Installer legt `.venv` an (mit `uv`, falls installiert, sonst mit Python 3.11+ aus Homebrew), installiert
alle Abhängigkeiten und prüft, dass sie laden. Er ist gefahrlos wiederholbar und lädt kein Modell.
Ohne Installer geht es auch von Hand:
`python3 -m venv .venv && ./.venv/bin/python -m pip install PyQt6 sounddevice pynput requests numpy sherpa-onnx soundfile huggingface_hub 'onnx-asr[cpu,hub]==0.10.2'`

Danach `./.venv/bin/python gui.py` starten oder **`Dictate starten.command`** doppelklicken.
Für Diktat ganz ohne Internet: **`Parakeet-Modell-laden.command`** doppelklicken. Das Skript lädt das
mehrsprachige v3-Modell (ca. 640 MB, festgelegte Revision) und stellt Kodiktat auf den lokalen Anbieter
mit `auto`. Hotkey, Aufnahmeart und CPU-Threads bleiben erhalten. Mit dem Argument `de` lädt es
stattdessen Primeline. Laufende Instanzen bei Bedarf manuell neu starten.

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
python -m pip install PyQt6 sounddevice pynput requests numpy sherpa-onnx soundfile huggingface_hub 'onnx-asr[cpu,hub]==0.10.2'
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
- **Einstellungen**: Anbieter, Modus (halten/umschalten), Hotkey, Modell, lokale Sprache (`auto`/`de`/`en`), CPU-Threads (lokal; 4 passt
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
  "local_stt_num_threads": 4,
  "local_stt_language": "auto",
  "model": "parakeet-tdt-0.6b-v3-int8"
}
```

Gültige Anbieter: `groq`, `openai`, `yorik`, `parakeet_local`.

## Lokale Modelle und Python-API

| Modus | Tatsächliches Modell | Verhalten |
|---|---|---|
| `auto` (neuer Standard) | NVIDIA Parakeet TDT 0.6B v3, int8 | erkennt Sprache automatisch, 25 unterstützte Sprachen inkl. DE/EN |
| `en` | dasselbe v3-Modell | Auswahl für englische Aufnahmen; Sprache wird weiterhin automatisch erkannt |
| `de` | Parakeet Primeline, int8 | deutsches Spezialmodell |

`en` erzwingt kein Englisch. Kodiktat übergibt dem v3-Modell keinen Sprachparameter und übersetzt
nicht. Gemischte Sprache kann erkannt werden; sehr kurze Wechsel, Akzente, Eigennamen und Störgeräusche
können Fehler verursachen. Ein gewählter Modus ist keine Angabe über die tatsächlich erkannte Sprache.

Beide Modelle liegen getrennt unter `~/.local/share/dictate/models/`:
`parakeet-tdt-0.6b-v3-onnx/` für `auto`/`en`, der bisherige Ordner
`parakeet-primeline-onnx/` für `de`. Die bisherigen `MODEL_DIR`, `MODEL_REPO`, `MODEL_REVISION`
und `MODEL_FILES` bleiben als Primeline-Aliase bestehen. Neue Verbraucher verwenden `model_info()`.
Die festgelegten Revisionen stehen ausschließlich in [local_stt.py](local_stt.py) und werden auch
von `model_info()` ausgegeben. Pro Modell werden etwa 640 MB geladen. Beide dürfen installiert bleiben.
Das Vorhandensein der Dateien wird geprüft; beschädigte ONNX-Dateien fallen beim Laden auf.

Bestehende Konfigurationen mit `model: "parakeet-primeline-int8"` und ohne `local_stt_language`
werden beim Lesen als `de` behandelt. So bleibt eine bisherige explizite Auswahl erhalten.
Für den Wechsel auf v3 in Settings `auto` wählen und dieses Modell herunterladen.
`local_stt_language` hat Vorrang vor dem alten `model`-Anzeigefeld. Explizit konfigurierte
Cloud-Anbieter bleiben erhalten. Neue Konfigurationen starten lokal mit `auto`.

```python
import local_stt

# Einmalig, bewusst mit Internet; für de separat aufrufen.
local_stt.download_model(progress_cb=print, language="auto")
assert local_stt.model_installed(language="auto")

# Danach offline; Laden/Erkennen laden niemals Dateien nach.
recognizer = local_stt.preload(num_threads=4, language="auto")
text = recognizer.transcribe(audio)  # int16 oder float [-1, 1], Mono, 16 kHz
info = local_stt.model_info(language="auto")  # JSON-fähig, ohne Laden
# identische Auswahl: get_recognizer(num_threads=4, language="auto")
# Bisherige Positionsargumente für Threads bzw. Download-Callback bleiben gültig.
```

`model_info()` liefert `language` (gewählter Modus), `model_id`, `repo_id`, `revision`, `model_dir`,
`files`, `backend`, `provider`, `automatic_language_detection` und `language_forced`.
Die geladene Auswahl steht außerdem in `recognizer.model_info`. Modus und Modellrevision erscheinen
im Diktat-Log, ohne den erkannten Text. Ein Wechsel von Modus, Modell oder Threadzahl baut den
Singleton neu auf. Fehlende Modelle, ungültige Modi oder Ladefehler werden sichtbar gemeldet;
es gibt keinen Rückfall auf Primeline oder einen Cloud-Dienst.

Für nachgelagerte Wortzeiten liefert `recognizer.transcribe_with_timestamps(audio)` ein Dictionary
mit `text`, `tokens`, `timestamps` und `model_info`. Zeitmarken sind **Token-Anfangszeiten in Sekunden**
bezogen auf das gesamte übergebene Audio, auch über Stückgrenzen hinweg. Das sind keine fertigen
Wortintervalle: Die Laufzeiten liefern Teilstücke mit führenden Leerzeichen als Wortanfang
(im Modellvokabular `▁`); Verbraucher müssen diese selbst
gruppieren. Wortenden lassen sich daraus nur abschätzen. Die Funktion nutzt dieselbe Modellauswahl,
Pegelhebung und Aufteilung wie `transcribe()`, das weiterhin nur `str` liefert.

Lange Aufnahmen werden an leisen Stellen geteilt: v3 in höchstens 25 Sekunden, Primeline weiterhin
in höchstens 90 Sekunden. Leise Stücke werden begrenzt angehoben, leere lange Ergebnisse nochmals
in kürzeren Stücken versucht. Schnittgrenzen können Wörter trennen oder Kontext verlieren.
Reine digitale Stille ergibt leeren Text; dies ist kein Sprachaktivitätsfilter für Raumgeräusche.

Prüfungen ohne Modell oder Mikrofon:

```bash
./.venv/bin/python -m unittest discover -s tests -v
```

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
schreibt Meetings mit, **Kodiktat** diktiert, weitere Werkzeuge nutzen lokale
Spracherkennungsmodelle.

## 🤝 Herkunft und Lizenz

Kodiktat ist ein **Fork von [winidi/dictate](https://github.com/winidi/dictate)** (MIT) und baut auf
dessen Aufnahme-, Hotkey- und Anbieterlogik auf. Dazu kamen die macOS-Fassung (Quartz-Hotkey, Tipp-
Freigabe, Pegelanzeige, Menüleistensymbol, rotes Abzeichen, Archiv je Aufnahme) und die deutsche
Ausrichtung. Der Upstream bleibt als Git-Remote `upstream` eingebunden.

Modelle: **CC-BY-4.0**. Das mehrsprachige Basismodell stammt von
[NVIDIA](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), die verwendete int8-ONNX-Konvertierung
von [istupakov](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx).
Das deutsche Feintuning stammt von [Primeline](https://huggingface.co/primeline), dessen ONNX-Export
von [flozen1981](https://huggingface.co/flozen1981/parakeet-primeline-onnx).
Laufzeiten: [onnx-asr](https://github.com/istupakov/onnx-asr) (MIT),
[ONNX Runtime](https://github.com/microsoft/onnxruntime) (MIT) und
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (Apache-2.0). Die Modelllizenzen gelten
unabhängig von der MIT-Lizenz dieses Programms.

**Lizenz: MIT** – siehe [LICENSE](LICENSE). Der ursprüngliche Urheberhinweis (winidi, 2026) bleibt
erhalten.
