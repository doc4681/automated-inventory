#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  DOPPIO CLICK QUI per CREARE le schede prodotto su Shopify.
#  Le schede vengono create come BOZZA (DRAFT): NON sono pubblicate,
#  le controlli e le pubblichi tu dal pannello Shopify.
# ════════════════════════════════════════════════════════════════════

cd "$(dirname "$0")" || { echo "Cartella non trovata"; read -r; exit 1; }

clear
echo "╔══════════════════════════════════════════════╗"
echo "║  VROOMI — Newsletter → Shopify   (CREA BOZZE) ║"
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

# ── Conferma esplicita ──────────────────────────────────────────────────────
echo "Sto per creare le schede prodotto MANCANTI come BOZZA su Shopify Vroomi."
echo "Le schede già presenti (stesso SKU) vengono saltate automaticamente."
echo "Si aprirà una finestra di Chrome: NON chiuderla."
echo ""
read -rp "Scrivi  CREA  e premi Invio per confermare (o chiudi per annullare): " conferma
if [[ "$conferma" != "CREA" ]]; then
  echo "Annullato. Non è stato creato nulla."
  read -rp "Premi Invio per chiudere…" _; exit 0
fi

echo ""
echo "▶ Creazione in corso… (può durare a lungo; se Chrome si blocca riparte da solo)"
echo ""
./.venv/bin/python run.py --apply

echo ""
echo "────────────────────────────────────────────────"
echo "✅ Finito. Le schede sono state create come BOZZA (DRAFT) su Shopify."
echo "   Controllale su:  https://admin.shopify.com/store/vroomimodels/products"
echo "   Trovi il dettaglio nel file  output/report_...csv"
read -rp "Premi Invio per chiudere…" _
