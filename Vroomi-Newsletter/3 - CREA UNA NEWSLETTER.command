#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  DOPPIO CLICK QUI per creare le schede di UNA SOLA newsletter.
#  Utile per lavorare un brand alla volta o per una prova mirata.
#  Le schede vengono create come BOZZA (DRAFT).
# ════════════════════════════════════════════════════════════════════

cd "$(dirname "$0")" || { echo "Cartella non trovata"; read -r; exit 1; }

clear
echo "╔══════════════════════════════════════════════╗"
echo "║  VROOMI — Newsletter → Shopify  (UNA SOLA)    ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Primo avvio: crea l'ambiente Python e installa le dipendenze ─────────────
if [[ ! -x ".venv/bin/python" ]]; then
  echo "▶ Primo avvio: preparo l'ambiente (1-2 minuti)…"
  if ! python3 -m venv .venv; then
    echo "❌ Python 3 non trovato. Installa Python 3 da python.org e riprova."
    read -rp "Premi Invio per chiudere…" _; exit 1
  fi
  ./.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
  echo "▶ Installo le dipendenze…"
  if ! ./.venv/bin/python -m pip install -r requirements.txt; then
    echo "❌ Errore nell'installazione delle dipendenze."
    read -rp "Premi Invio per chiudere…" _; exit 1
  fi
fi

# ── Controllo credenziali ───────────────────────────────────────────────────
if grep -q "tua-email@esempio.com" credenziali.env 2>/dev/null; then
  echo "⚠️  Devi ancora inserire le credenziali."
  echo "   Apri il file  credenziali.env  con TextEdit, compila e salva."
  echo ""
  read -rp "Premi Invio per chiudere…" _; exit 1
fi

# ── Chiedi l'ID della newsletter ────────────────────────────────────────────
echo "Serve l'ID della newsletter: è il numero tra parentesi che vedi nella"
echo "PROVA, ad esempio in  « KK-SCALE (15280) »  l'ID è  15280 ."
echo "(Puoi metterne anche più di una separate da virgola: 15280,15279)"
echo ""
read -rp "Incolla qui l'ID e premi Invio: " nlid

# tieni solo cifre e virgole
nlid=$(echo "$nlid" | tr -cd '0-9,')
if [[ -z "$nlid" ]]; then
  echo "Nessun ID valido inserito. Annullato."
  read -rp "Premi Invio per chiudere…" _; exit 1
fi

echo ""
echo "Sto per creare in BOZZA le schede MANCANTI della/e newsletter:  $nlid"
echo "Le schede con SKU già presente vengono saltate. Si aprirà Chrome: non chiuderla."
echo ""
read -rp "Scrivi  CREA  e premi Invio per confermare (o chiudi per annullare): " conferma
if [[ "$conferma" != "CREA" ]]; then
  echo "Annullato. Non è stato creato nulla."
  read -rp "Premi Invio per chiudere…" _; exit 0
fi

echo ""
echo "▶ Creazione in corso… (se Chrome si blocca riparte da solo)"
echo ""
./.venv/bin/python run.py --newsletter "$nlid" --apply

echo ""
echo "────────────────────────────────────────────────"
echo "✅ Finito. Schede create come BOZZA (DRAFT) su Shopify."
echo "   Controlla su:  https://admin.shopify.com/store/vroomimodels/products"
read -rp "Premi Invio per chiudere…" _
