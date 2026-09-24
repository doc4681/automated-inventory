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

# shellcheck source=_prepara.sh
source ./_prepara.sh
prepara_tutto

echo "▶ Avvio la prova. Si aprirà una finestra di Chrome: NON chiuderla."
echo "  (al termine vedrai il riepilogo qui sotto)"
echo ""
esegui_run --no-enrich

echo ""
echo "────────────────────────────────────────────────"
if [[ $ESITO_RUN -eq 0 ]]; then
  echo "✅ Prova finita. Non è stata creata nessuna scheda."
  echo "   Per creare davvero le schede (in BOZZA), usa lo script:"
  echo "   « 2 - CREA SCHEDE DRAFT »  oppure  « 3 - CREA UNA NEWSLETTER »"
else
  echo "❌ La prova ha avuto errori (codice $ESITO_RUN)."
  echo "   Leggi il messaggio qui sopra. Se non è chiaro, manda a Matteo il file:"
  echo "   output/ultima_run.log"
fi
read -rp "Premi Invio per chiudere…" _
