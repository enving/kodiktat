#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"
# Optional: ./Parakeet-Modell-laden.command de (Primeline) or en (v3).
./.venv/bin/python - "${1:-auto}" <<'PY'
import sys
import core
import local_stt

language = sys.argv[1]
info = local_stt.model_info(language)  # validate before download/config writes
local_stt.download_model(print, language=language)
assert local_stt.model_installed(language), "Parakeet-Modell ist unvollständig"
cfg = core.load_config()
cfg.update({
    "provider": "parakeet_local",
    "model": info["model_id"],
    "local_stt_language": language,
})
# Keep existing hotkey, recording mode, thread count and provider credentials.
core.save_config(cfg)
print(f"Fertig: {info['model_id']}, Modus {language}, CPU, offline.")
PY

echo "Kodiktat bei Bedarf manuell neu starten."
read -n 1 '?Taste drücken, um dieses Fenster zu schließen.'
