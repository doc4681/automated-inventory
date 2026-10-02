#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  Installa / aggiorna Vroomi (pannello completo) senza il blocco di macOS.
#
#  Si lancia incollando nel Terminale (una riga sola):
#    curl -fsSL https://raw.githubusercontent.com/doc4681/automated-inventory/main/installa.sh | bash
#
#  Perché: i file scaricati da browser/Drive/WhatsApp ricevono da macOS il
#  "marchio" di quarantena e al doppio click compare « Apple non è in grado di
#  verificare… ». I file scaricati con curl NON lo ricevono: gli script si
#  aprono subito, ogni volta.
#
#  Cartella: ~/Vroomi. Per installare/aggiornare un'altra cartella passala
#  come argomento:
#    curl -fsSL …/installa.sh | bash -s -- "$HOME/Desktop/Vroomi"
#  Aggiornando, NON vengono toccati: credenziali.env, dati/, RISULTATO/, logs/,
#  l'ambiente .venv e i report delle newsletter. Vengono solo sostituiti i
#  file del programma.
# ════════════════════════════════════════════════════════════════════
set -euo pipefail

DEST="${1:-$HOME/Vroomi}"
REF="${VROOMI_REF:-main}"                 # ramo da scaricare (per le prove)
ZIP_URL="https://codeload.github.com/doc4681/automated-inventory/zip/refs/heads/$REF"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "▶ Scarico l'ultima versione di Vroomi…"
curl -fsSL "$ZIP_URL" -o "$TMP/repo.zip"
unzip -q "$TMP/repo.zip" -d "$TMP"
SRC=$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -1)
[[ -f "$SRC/app.py" && -d "$SRC/pannello" ]] || { echo "❌ Download incompleto: riprova."; exit 1; }

# Non installare sopra una cartella che non è Vroomi (es. la Home per errore)
if [[ -d "$DEST" && -n "$(ls -A "$DEST" 2>/dev/null)" && ! -f "$DEST/app.py" ]]; then
  echo "❌ La cartella $DEST esiste già e non è una cartella Vroomi: non la tocco."
  echo "   Scegline un'altra:  curl -fsSL …/installa.sh | bash -s -- \"\$HOME/Vroomi\""
  exit 1
fi
NUOVA=0; [[ -f "$DEST/app.py" ]] || NUOVA=1

mkdir -p "$DEST"
# Copia i file del programma (il download non contiene mai dati locali o password)
( cd "$SRC" && find . -type f -print0 |
    while IFS= read -r -d '' f; do
      mkdir -p "$DEST/$(dirname "$f")"
      cp "$f" "$DEST/$f"
    done )

# Password: se manca credenziali.env, riusa quello di una copia vecchia
if [[ ! -f "$DEST/credenziali.env" ]]; then
  OLD=$(find "$HOME/Desktop" "$HOME/Downloads" "$HOME/Documents" "$HOME" -maxdepth 3 \
          -name credenziali.env -not -path "$DEST/*" 2>/dev/null | head -1 || true)
  if [[ -n "$OLD" ]]; then
    cp "$OLD" "$DEST/credenziali.env"
    chmod 600 "$DEST/credenziali.env"
    echo "▶ Password copiate da: $OLD"
  fi
fi

find "$DEST" -name "*.command" -exec chmod +x {} +
chmod +x "$DEST/pipeline/run.sh" 2>/dev/null || true
# Per sicurezza: togli l'eventuale quarantena rimasta (non dà errore se non c'è)
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

echo ""
if (( NUOVA )); then
  echo "✅ Vroomi installato in:  $DEST"
else
  echo "✅ Vroomi aggiornato in:  $DEST  (password e dati intatti)"
fi
if [[ ! -f "$DEST/credenziali.env" ]]; then
  echo "ℹ️  Le password si inseriscono dal pannello: ⚙️ Impostazioni."
fi
echo "   Per aggiornare in futuro rilancia la stessa riga."

# Sul Mac apre subito il pannello (in una finestra del Terminale tutta sua)
if [[ "$(uname)" == "Darwin" ]]; then
  echo "▶ Apro il pannello…"
  open "$DEST/AVVIA PANNELLO.command"
fi
