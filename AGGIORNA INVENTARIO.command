#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  DOPPIO CLICK QUI per aggiornare il catalogo carmodel + MCWS.
# ════════════════════════════════════════════════════════════════════
# Tutta la logica sta in run_local.sh (unica fonte di verità: questo file
# e lo scheduler automatico usano lo stesso script).
# Il risultato finale finisce in:  RISULTATO/merged_products_LATEST.csv

cd "$(dirname "$0")" || { echo "Cartella non trovata"; exit 1; }

bash run_local.sh
STATUS=$?

echo ""
if [[ $STATUS -eq 0 ]]; then
  echo "✅ FATTO. File da importare su Shopify:"
  echo "   RISULTATO/merged_products_LATEST.csv"
else
  echo "⚠️  Run terminata con errori — i dati precedenti sono stati preservati."
  echo "   Controlla i log nella cartella  logs/"
fi
echo ""
read -rp "Premi Invio per chiudere questa finestra..." _
