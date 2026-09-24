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

# shellcheck source=_prepara.sh
source ./_prepara.sh
prepara_tutto

# ── Chiedi l'ID della newsletter ────────────────────────────────────────────
echo "Serve l'ID della newsletter: è il numero che vedi nella PROVA,"
echo "ad esempio in  « KK-SCALE (id 15280) »  l'ID è  15280 ."
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
# accetta anche 'crea' / spazi prima o dopo
conferma=$(echo "$conferma" | tr -d '[:space:]' | tr '[:lower:]' '[:upper:]')
if [[ "$conferma" != "CREA" ]]; then
  echo "Annullato. Non è stato creato nulla."
  read -rp "Premi Invio per chiudere…" _; exit 0
fi

echo ""
echo "▶ Creazione in corso… (se Chrome si blocca riparte da solo)"
echo ""
esegui_run --newsletter "$nlid" --apply

echo ""
echo "────────────────────────────────────────────────"
if [[ $ESITO_RUN -eq 0 ]]; then
  echo "✅ Finito. Leggi il riepilogo qui sopra (quante schede CREATE / già esistenti)."
  echo "   Le schede nuove sono in BOZZA (DRAFT) su:"
  echo "   https://admin.shopify.com/store/vroomimodels/products"
else
  echo "❌ Ci sono stati errori (codice $ESITO_RUN): non tutto è andato a buon fine."
  echo "   Leggi il messaggio qui sopra. Se non è chiaro, manda a Matteo il file:"
  echo "   output/ultima_run.log"
fi
read -rp "Premi Invio per chiudere…" _
