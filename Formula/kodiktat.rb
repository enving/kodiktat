class Kodiktat < Formula
  include Language::Python::Virtualenv

  desc "Diktieren per Hotkey: lokal (Parakeet), Deutsch und Englisch"
  homepage "https://github.com/enving/kodiktat"
  license "MIT"
  head "https://github.com/enving/kodiktat.git", branch: "main"

  depends_on :macos
  depends_on "python@3.13"

  # Gleiche Liste wie install-macos.sh und README; onnx-asr ist festgepinnt.
  PIP_PACKAGES = [
    "PyQt6", "sounddevice", "pynput", "requests", "numpy",
    "sherpa-onnx", "soundfile", "huggingface_hub", "onnx-asr[cpu,hub]==0.10.2"
  ].freeze

  def install
    venv = virtualenv_create(libexec, "python3.13")
    # Keine Ressourcen-Liste mit Hashes: Abhängigkeiten kommen direkt von PyPI.
    # pip_install erzwingt Quellbau (--no-binary) und scheitert an PyQt6; deshalb
    # direkt mit fertigen Wheels, sonst bricht die Installation ab.
    system "python3.13", "-m", "pip", "--python=#{venv.root}/bin/python",
           "install", "--only-binary=:all:", *PIP_PACKAGES

    libexec.install "gui.py", "core.py", "local_stt.py", "evdev_listener.py"

    # Qt-SQL-Treiber brauchen Fremdbibliotheken (Postgres, ODBC, Mimer), die hier
    # fehlen; Kodiktat nutzt keine SQL-Datenbank.
    sqldrivers = libexec/"lib/python3.13/site-packages/PyQt6/Qt6/plugins/sqldrivers"
    rm_r(sqldrivers) if sqldrivers.exist?

    (bin/"kodiktat").write <<~SH
      #!/bin/bash
      exec "#{libexec}/bin/python" "#{libexec}/gui.py" "$@"
    SH
  end

  def caveats
    <<~EOS
      Ersteinrichtung:
        1. Starten: kodiktat
        2. In den Einstellungen Anbieter "parakeet_local" bzw. lokale Sprache "auto"
           wählen und das Modell herunterladen (einmalig, Internet nötig, ca. 640 MB).

      macOS fragt beim ersten Start nach Mikrofon und Bedienungshilfen
      (Systemeinstellungen > Datenschutz & Sicherheit). Danach die App neu starten.
    EOS
  end

  test do
    assert_path_exists libexec/"bin/python"
    system libexec/"bin/python", "-c", "import PyQt6.QtWidgets, sherpa_onnx, onnx_asr, sounddevice"
    # Nur lesen, kein __pycache__ im Keg (Test-Sandbox erlaubt das nicht).
    system libexec/"bin/python", "-c",
           "import ast, sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]",
           libexec/"gui.py", libexec/"core.py", libexec/"local_stt.py"
  end
end
