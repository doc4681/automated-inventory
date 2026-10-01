#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  Installa / aggiorna Vroomi-Newsletter senza il blocco di macOS.
#
#  Si lancia incollando nel Terminale (una riga sola):
#    curl -fsSL https://raw.githubusercontent.com/doc4681/automated-inventory/main/Vroomi-Newsletter/installa.sh | bash
#
#  Perché: i file scaricati da browser/Drive/WhatsApp ricevono da macOS il
#  "marchio" di quarantena, e al doppio click compare « Apple non è in grado di
#  verificare… ». I file scaricati con curl NON lo ricevono, quindi gli script
#  si aprono subito, ogni volta, senza xattr né "Apri comunque".
#
#  Cartella: ~/Vroomi-Newsletter (diversa? passala come argomento:
#    curl -fsSL …/installa.sh | bash -s -- "$HOME/Desktop/Vroomi-Newsletter")
#  Aggiornando, credenziali.env, output/ e l'ambiente .venv restano intatti.
# ════════════════════════════════════════════════════════════════════
set -euo pipefail

DEST="${1:-$HOME/Vroomi-Newsletter}"
ZIP_URL="https://codeload.github.com/doc4681/automated-inventory/zip/refs/heads/main"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "▶ Scarico l'ultima versione…"
curl -fsSL "$ZIP_URL" -o "$TMP/repo.zip"
unzip -q "$TMP/repo.zip" -d "$TMP"
SRC=$(find "$TMP" -maxdepth 2 -type d -name Vroomi-Newsletter | head -1)
[[ -n "$SRC" ]] || { echo "❌ Cartella Vroomi-Newsletter non trovata nel download."; exit 1; }

mkdir -p "$DEST"
# Copia tutto tranne i dati locali (credenziali, report, ambiente Python)
( cd "$SRC" && find . -type f ! -name credenziali.env ! -path './output/*' ! -path './.venv/*' -print0 |
    while IFS= read -r -d '' f; do
      mkdir -p "$DEST/$(dirname "$f")"
      cp "$f" "$DEST/$f"
    done )
mkdir -p "$DEST/output"

# Se manca credenziali.env, riusa quello di una copia vecchia (zip da Drive)
if [[ ! -f "$DEST/credenziali.env" ]]; then
  OLD=$(find "$HOME/Desktop" "$HOME/Downloads" "$HOME/Documents" -maxdepth 3 \
          -path "*Vroomi-Newsletter*/credenziali.env" 2>/dev/null | head -1 || true)
  if [[ -n "$OLD" ]]; then
    cp "$OLD" "$DEST/credenziali.env"
    echo "▶ Credenziali copiate da: $OLD"
  fi
fi

chmod +x "$DEST"/*.command
# Per sicurezza: togli l'eventuale quarantena rimasta (non dà errore se non c'è)
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

echo ""
echo "✅ Vroomi-Newsletter pronto in:  $DEST"
if [[ ! -f "$DEST/credenziali.env" ]]; then
  echo "⚠️  Manca credenziali.env: copia lì dentro il tuo file credenziali.env"
  echo "   (oppure crealo da credenziali.esempio.env)."
fi
echo "   Usa SOLO questa cartella (cancella le copie vecchie scaricate da Drive)."
open "$DEST" 2>/dev/null || true
