#!/usr/bin/env bash
# aggiorna_inventario.command
# Doppio click dal Finder per aggiornare l'inventario completo.
# Carica le credenziali MCWS da ~/.env.vroomi (mai committato).

cd /Users/matteosanguineti/automated-inventory

# Carica credenziali
if [[ -f "$HOME/.env.vroomi" ]]; then
  source "$HOME/.env.vroomi"
else
  echo "ERRORE: ~/.env.vroomi non trovato."
  echo "Crea il file con:"
  echo '  export MCWS_USERNAME="tua@email.com"'
  echo '  export MCWS_PASSWORD="tuapassword"'
  read -rp "Premi Invio per chiudere..." _
  exit 1
fi

# ── Impedisce il sleep del Mac per tutta la durata dello script ──────────────
caffeinate -dims &
CAFFEINATE_PID=$!
trap "kill $CAFFEINATE_PID 2>/dev/null" EXIT

# ── Header ───────────────────────────────────────────────────────────────────
clear
echo "╔══════════════════════════════════════════════════════╗"
echo "║         VROOMI — AGGIORNAMENTO INVENTARIO            ║"
echo "║         $(date '+%A %d %B %Y  %H:%M')               ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

T_START=$(date +%s)
export RUN_TIMESTAMP=$(date '+%Y-%m-%d_%H%M')

echo "  Run timestamp: $RUN_TIMESTAMP"
echo ""

# ── STEP 1: Scraper carmodel.com ─────────────────────────────────────────────
echo "▶ [1/3] Scraping carmodel.com..."
python3 scraper/carmodel_scraper.py
echo ""

# ── STEP 2: Download MCWS ────────────────────────────────────────────────────
echo "▶ [2/3] Download inventario MCWS..."
python3 downloader/mcws_downloader.py
echo ""

# ── STEP 3: Merger ───────────────────────────────────────────────────────────
echo "▶ [3/3] Merge dei cataloghi..."
python3 merger/product_merger.py
echo ""

# ── Riepilogo finale ─────────────────────────────────────────────────────────
T_END=$(date +%s)
DURATA=$((T_END - T_START))

RIGHE_CARMODEL=$(tail -n +2 "scraper/output/carmodel_scraped_${RUN_TIMESTAMP}.csv" 2>/dev/null | wc -l | tr -d ' ')
RIGHE_MCWS=$(tail -n +2 "downloader/output/mcws_inventory_${RUN_TIMESTAMP}.csv" 2>/dev/null | wc -l | tr -d ' ')
RIGHE_MERGED=$(tail -n +2 "merger/output/merged_products_${RUN_TIMESTAMP}.csv" 2>/dev/null | wc -l | tr -d ' ')

echo "╔══════════════════════════════════════════════════════╗"
echo "║                  RIEPILOGO FINALE                    ║"
echo "╠══════════════════════════════════════════════════════╣"
printf "║  Prodotti carmodel.com : %-28s║\n" "$RIGHE_CARMODEL"
printf "║  Prodotti MCWS         : %-28s║\n" "$RIGHE_MCWS"
printf "║  Match (merged)        : %-28s║\n" "$RIGHE_MERGED"
printf "║  Durata                : %-25s s ║\n" "$DURATA"
echo "╠══════════════════════════════════════════════════════╣"
printf "║  Output: merger/output/merged_products_%-14s║\n" "${RUN_TIMESTAMP}.csv"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

read -rp "Premi Invio per chiudere..." _
