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

# shellcheck source=_prepara.sh
source ./_prepara.sh
prepara_tutto

# ── Conferma esplicita ──────────────────────────────────────────────────────
echo "Sto per creare le schede prodotto MANCANTI come BOZZA su Shopify Vroomi."
echo "Le schede già presenti (stesso SKU) vengono saltate automaticamente."
echo "Si aprirà una finestra di Chrome: NON chiuderla."
echo ""
read -rp "Scrivi  CREA  e premi Invio per confermare (o chiudi per annullare): " conferma
# accetta anche 'crea' / spazi prima o dopo
conferma=$(echo "$conferma" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')
if [[ "$conferma" != "CREA" ]]; then
  echo "Annullato. Non è stato creato nulla."
  read -rp "Premi Invio per chiudere…" _; exit 0
fi

echo ""
echo "▶ Creazione in corso… (può durare a lungo; se Chrome si blocca riparte da solo)"
echo ""
esegui_run --apply

echo ""
echo "────────────────────────────────────────────────"
if [[ $ESITO_RUN -eq 0 ]]; then
  echo "✅ Finito. Leggi il riepilogo qui sopra (quante schede CREATE / già esistenti)."
  echo "   Le schede nuove sono in BOZZA (DRAFT) su:"
  echo "   https://admin.shopify.com/store/vroomimodels/products"
  echo "   Trovi il dettaglio nel file  output/report_...csv"
else
  echo "❌ Ci sono stati errori (codice $ESITO_RUN): non tutto è andato a buon fine."
  echo "   Leggi il messaggio qui sopra. Se non è chiaro, manda a Matteo il file:"
  echo "   output/ultima_run.log"
fi
read -rp "Premi Invio per chiudere…" _
