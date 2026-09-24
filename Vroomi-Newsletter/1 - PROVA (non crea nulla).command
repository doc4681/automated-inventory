#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  DOPPIO CLICK QUI per fare una PROVA.
#  Mostra quante schede NUOVE ci sarebbero da creare, SENZA scrivere
#  niente su Shopify. Sicuro: non crea e non modifica nulla.
# ════════════════════════════════════════════════════════════════════

cd "$(dirname "$0")" || { echo "Cartella non trovata"; read -r; exit 1; }

clear
echo "╔══════════════════════════════════════════════╗"
echo "║   VROOMI — Newsletter → Shopify   (PROVA)     ║"
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

echo "▶ Avvio la prova. Si aprirà una finestra di Chrome: NON chiuderla."
echo "  (al termine vedrai il riepilogo qui sotto)"
echo ""
./.venv/bin/python run.py --no-enrich

echo ""
echo "────────────────────────────────────────────────"
echo "✅ Prova finita. Non è stata creata nessuna scheda."
echo "   Per creare davvero le schede (in BOZZA), usa lo script:"
echo "   « 2 - CREA SCHEDE DRAFT »"
read -rp "Premi Invio per chiudere…" _
