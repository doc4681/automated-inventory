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
#
#  Lo usa anche il pannello per «Aggiorna adesso» (pannello/aggiornamenti.py),
#  con VROOMI_NO_OPEN=1: il pannello lo riapre da sé dopo aver chiuso il vecchio.
#  In .versione resta scritta la versione installata (codice del commit + ramo).
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
# Versione scaricata: GitHub scrive il codice del commit come commento dello zip
VERSIONE=$(unzip -z "$TMP/repo.zip" 2>/dev/null | grep -Eo '^[0-9a-f]{40}$' | head -1 || true)

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

# Password: se manca credenziali.env, riusa quello di una copia vecchia. Prima
# quello della cartella Vroomi-Newsletter installata dal Terminale (è quello che
# il collaboratore usa davvero), poi il più RECENTE tra gli altri; scarta i file
# ancora da compilare (password vuota o email di esempio).
cred_valido() {
  grep -Eq "^[[:space:]]*export[[:space:]]+MCWS_PASSWORD=['\"]?[^'\"[:space:]]" "$1" &&
    ! grep -q "tua-email@esempio.com" "$1"
}
if [[ ! -f "$DEST/credenziali.env" ]]; then
  OLD=""
  if [[ -f "$HOME/Vroomi-Newsletter/credenziali.env" ]] && cred_valido "$HOME/Vroomi-Newsletter/credenziali.env"; then
    OLD="$HOME/Vroomi-Newsletter/credenziali.env"
  else
    while IFS= read -r -d '' f; do
      cred_valido "$f" || continue
      if [[ -z "$OLD" || "$f" -nt "$OLD" ]]; then OLD="$f"; fi    # il più recente
    done < <(find "$HOME/Desktop" "$HOME/Downloads" "$HOME/Documents" "$HOME" -maxdepth 3 \
               -name credenziali.env -not -path "$DEST/*" -print0 2>/dev/null || true)
  fi
  if [[ -n "$OLD" ]]; then
    cp "$OLD" "$DEST/credenziali.env"
    chmod 600 "$DEST/credenziali.env"
    echo "▶ Password copiate da: $OLD"
  fi
fi

# Versione installata: il pannello la confronta con GitHub per proporre gli aggiornamenti
if [[ -n "$VERSIONE" ]]; then
  printf '%s\n%s\n' "$VERSIONE" "$REF" > "$DEST/.versione"
else
  rm -f "$DEST/.versione"        # sconosciuta: il pannello proporrà di aggiornare
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

# Sul Mac apre subito il pannello (in una finestra del Terminale tutta sua),
# tranne quando l'aggiornamento parte dal pannello stesso (lo riapre lui)
if [[ "$(uname)" == "Darwin" && "${VROOMI_NO_OPEN:-0}" != "1" ]]; then
  echo "▶ Apro il pannello…"
  open "$DEST/AVVIA PANNELLO.command"
fi
