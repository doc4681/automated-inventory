#!/usr/bin/env bash
# run.sh — la pipeline completa, NON interattiva. Unica fonte di verità: la usano
# il pulsante "AGGIORNA INVENTARIO.command", il pannello e la pianificazione automatica.
#
#   1. scraper carmodel.com   → dati/carmodel/carmodel_scraped_<ts>.csv
#   2. download listino MCWS  → dati/mcws/mcws_inventory_<ts>.csv
#   3. merge                  → dati/merged/merged_products_<ts>.csv
#                               + RISULTATO/merged_products_LATEST.csv
#   4. (opzionale) note → Shopify, se ENABLE_SHOPIFY=1
#
# Protezioni:
#   • una scrape/download fallita o sospetta NON sovrascrive i dati buoni
#     (il file viene spostato in dati/scartati/ e il merge saltato)
#   • una sola run alla volta (lock)
#   • un log per run in logs/run_<ts>.log + notifica macOS a fine run
#
# Credenziali: credenziali.env nella cartella del progetto e/o ~/.env.vroomi.

set -uo pipefail

PIPE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$PIPE")"
cd "$REPO" || { echo "ERRORE: $REPO non trovato"; exit 1; }

# ── Soglie di validazione (override via env) ─────────────────────────────────
MIN_CARMODEL_ROWS="${MIN_CARMODEL_ROWS:-200}"   # min righe attese dallo scraper
MIN_MCWS_ROWS="${MIN_MCWS_ROWS:-1000}"          # min righe attese dall'inventario MCWS
MAX_DROP_PCT="${MAX_DROP_PCT:-50}"              # calo % max tollerato vs run precedente
MIN_BRAND_COVERAGE="${MIN_BRAND_COVERAGE:-90}"  # % min di brand attesi presenti nello scrape
KEEP_LOGS="${KEEP_LOGS:-30}"                    # n. di log da conservare
KEEP_DATA="${KEEP_DATA:-15}"                    # n. di CSV da conservare per cartella in dati/

# ── Logging per-run (prima di tutto, così anche gli errori iniziali finiscono nel log) ──
# RUN_TIMESTAMP può arrivare dal pannello (che così sa quale log mostrare).
export RUN_TIMESTAMP="${RUN_TIMESTAMP:-$(date '+%Y-%m-%d_%H%M')}"
export PYTHONUNBUFFERED=1                       # log in diretta, non a blocchi
LOG_DIR="$REPO/logs"; mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_${RUN_TIMESTAMP}.log"
exec > >(tee -a "$LOG_FILE") 2>&1
ls -1t "$LOG_DIR"/run_*.log 2>/dev/null | tail -n +$((KEEP_LOGS + 1)) | while read -r f; do rm -f "$f"; done

notify() {  # notify <titolo> <messaggio>
  /usr/bin/osascript -e "display notification \"$2\" with title \"$1\"" 2>/dev/null || true
  if [[ -n "${NOTIFY_WEBHOOK:-}" ]]; then
    curl -s -m 10 -X POST -H 'Content-Type: application/json' \
      -d "{\"text\":\"$1 — $2\"}" "$NOTIFY_WEBHOOK" >/dev/null 2>&1 || true
  fi
}

# ── Una sola run alla volta ──────────────────────────────────────────────────
LOCK_DIR="$REPO/logs/.run.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ -n "$OTHER_PID" ]] && kill -0 "$OTHER_PID" 2>/dev/null; then
    echo "⏭  Un'altra run è già in corso (pid $OTHER_PID): esco senza fare nulla."
    exit 0
  fi
  echo "(lock orfano di una run interrotta: lo rimuovo)"
  rm -rf "$LOCK_DIR"; mkdir "$LOCK_DIR"
fi
echo $$ > "$LOCK_DIR/pid"

# Impedisce lo stop del Mac finché questa run è viva (-w: caffeinate esce da solo con lei).
caffeinate -dims -w $$ &
trap 'rm -rf "$LOCK_DIR"' EXIT

echo "════════════════════════════════════════════════════════"
echo "VROOMI — AGGIORNAMENTO INVENTARIO"
echo "Avvio: $(date '+%A %d %B %Y  %H:%M:%S')  |  ts: $RUN_TIMESTAMP"
echo "════════════════════════════════════════════════════════"

# ── Credenziali ──────────────────────────────────────────────────────────────
# Se esistono entrambe, credenziali.env (nella cartella) ha la precedenza.
# shellcheck disable=SC1091
[[ -f "$HOME/.env.vroomi" ]] && source "$HOME/.env.vroomi"
# shellcheck disable=SC1091
[[ -f "$REPO/credenziali.env" ]] && source "$REPO/credenziali.env"
if [[ -z "${MCWS_USERNAME:-}" || -z "${MCWS_PASSWORD:-}" ]]; then
  echo "ERRORE: credenziali MCWS mancanti. Compila 'credenziali.env' nella cartella"
  echo "        (oppure ~/.env.vroomi) con MCWS_USERNAME e MCWS_PASSWORD."
  notify "Vroomi ⚠️ Inventario FALLITO" "Credenziali MCWS mancanti"
  exit 1
fi

# ── Python: virtualenv del progetto se presente ──────────────────────────────
if [[ -x "$REPO/.venv/bin/python" ]]; then PY="$REPO/.venv/bin/python"; else PY="$(command -v python3)"; fi
echo "Python: $PY"

# ── Helpers ──────────────────────────────────────────────────────────────────
rows() { [[ -f "$1" ]] && { local n; n=$(tail -n +2 "$1" 2>/dev/null | wc -l | tr -d ' '); echo "${n:-0}"; } || echo 0; }

prev_file() {  # file piu' recente con quel prefisso, ESCLUSO il run corrente
  ls -1t "$1"/${2}_*.csv 2>/dev/null | grep -v "_${RUN_TIMESTAMP}.csv" | head -1
}

# validate <file> <min_rows> <label> → 0 se valido, 1 se va scartato
validate() {
  local f="$1" minr="$2" label="$3" dir; dir="$(dirname "$f")"
  local now; now=$(rows "$f")
  if [[ ! -f "$f" ]]; then echo "  ✗ $label: file mancante"; return 1; fi
  if (( now < minr )); then echo "  ✗ $label: solo $now righe (< min $minr) — SCARTATO"; return 1; fi
  local pf; pf="$(prev_file "$dir" "$(basename "${f%_${RUN_TIMESTAMP}.csv}")")"
  if [[ -n "$pf" ]]; then
    local prev; prev=$(rows "$pf")
    if (( prev > 0 )) && (( now * 100 < prev * (100 - MAX_DROP_PCT) )); then
      echo "  ✗ $label: $now righe vs $prev precedenti (calo > ${MAX_DROP_PCT}%) — SCARTATO"
      return 1
    fi
    echo "  ✓ $label: $now righe (prec: $prev) — OK"
  else
    echo "  ✓ $label: $now righe (nessun riferimento precedente) — OK"
  fi
  return 0
}

reject() {  # sposta il file sospetto in dati/scartati/ così non viene riusato
  local f="$1" dir="$REPO/dati/scartati"; mkdir -p "$dir"
  [[ -f "$f" ]] && mv "$f" "$dir/" && echo "  → spostato in dati/scartati/"
  [[ -f "${f%.csv}.INCOMPLETO.txt" ]] && mv "${f%.csv}.INCOMPLETO.txt" "$dir/"
  return 0
}

prune() {  # prune <dir> <prefix> — conserva solo gli ultimi KEEP_DATA file
  ls -1t "$1"/${2}_*.csv 2>/dev/null | tail -n +$((KEEP_DATA + 1)) | while read -r f; do
    rm -f "$f" "${f%.csv}.INCOMPLETO.txt"
  done
}

# brand_coverage_ok <scraped_csv> → 0 se la copertura brand è sufficiente, 1 altrimenti
brand_coverage_ok() {
  "$PY" - "$1" "$REPO/config/Valid_Trademarks.txt" "$MIN_BRAND_COVERAGE" <<'PY'
import csv as _csv, sys, re
scraped, tmfile, minpct = sys.argv[1], sys.argv[2], int(sys.argv[3])
expected = set()
with open(tmfile, encoding="utf-8") as f:
    for line in f:
        name = re.sub(r'^\d+\s+', '', line.strip())
        if name:
            expected.add(name.upper())
got = set()
try:
    with open(scraped, newline='', encoding='utf-8') as f:
        for row in _csv.DictReader(f):
            t = (row.get('trademark') or '').strip().upper()
            if t:
                got.add(t)
except Exception as e:
    print(f"  ✗ copertura: errore lettura ({e})")
    sys.exit(1)
present = len(got & expected)
cov = 100 * present // len(expected) if expected else 100
mark = "✓" if cov >= minpct else "✗"
missing = sorted(expected - got)
print(f"  {mark} copertura brand: {present}/{len(expected)} = {cov}% (soglia {minpct}%)"
      + (f" — mancanti: {', '.join(missing[:12])}{'…' if len(missing) > 12 else ''}" if missing else ""))
sys.exit(0 if cov >= minpct else 1)
PY
}

T_START=$(date +%s)
FAILURES=()

CARMODEL_CSV="dati/carmodel/carmodel_scraped_${RUN_TIMESTAMP}.csv"
MCWS_CSV="dati/mcws/mcws_inventory_${RUN_TIMESTAMP}.csv"
MERGED_CSV="dati/merged/merged_products_${RUN_TIMESTAMP}.csv"

# ── STEP 1: Scraper carmodel.com ─────────────────────────────────────────────
echo ""; echo "▶ [1/4] Scraping carmodel.com..."
"$PY" pipeline/carmodel_scraper.py || echo "  (scraper uscito con errore)"
CARMODEL_OK=1
if ! validate "$CARMODEL_CSV" "$MIN_CARMODEL_ROWS" "carmodel"; then
  CARMODEL_OK=0; FAILURES+=("scraper"); reject "$CARMODEL_CSV"
elif ! brand_coverage_ok "$CARMODEL_CSV"; then
  # scrape parziale (troppi brand mancanti, es. Chrome morto a inizio run) → scarta
  CARMODEL_OK=0; FAILURES+=("scraper:copertura"); reject "$CARMODEL_CSV"
fi

# ── STEP 2: Download MCWS ────────────────────────────────────────────────────
echo ""; echo "▶ [2/4] Download inventario MCWS..."
"$PY" pipeline/mcws_downloader.py || echo "  (downloader uscito con errore)"
MCWS_OK=1
if ! validate "$MCWS_CSV" "$MIN_MCWS_ROWS" "mcws"; then
  MCWS_OK=0; FAILURES+=("downloader"); reject "$MCWS_CSV"
fi

# ── STEP 3: Merge (solo se entrambi gli input sono validi) ───────────────────
echo ""; echo "▶ [3/4] Merge dei cataloghi..."
MERGED_ROWS=0
if (( CARMODEL_OK == 1 && MCWS_OK == 1 )); then
  if "$PY" pipeline/product_merger.py; then
    MERGED_ROWS=$(rows "$MERGED_CSV")
    if (( MERGED_ROWS > 0 )); then
      mkdir -p "$REPO/RISULTATO"
      cp "$MERGED_CSV" "$REPO/RISULTATO/merged_products_LATEST.csv"
      echo "  ✓ risultato → RISULTATO/merged_products_LATEST.csv"
    fi
  else
    FAILURES+=("merger"); echo "  ✗ merger fallito"
  fi
else
  echo "  ⏭  Merge SALTATO: input non validi. Il risultato precedente resta com'era."
fi

# ── STEP 4 (OPZIONALE): Shopify — note → metafield custom.notes ──────────────
if [[ "${ENABLE_SHOPIFY:-0}" == "1" ]]; then
  echo ""; echo "▶ [4/4] Shopify: aggiorno metafield custom.notes..."
  if (( MERGED_ROWS > 0 )); then
    if [[ -z "${SHOPIFY_ADMIN_TOKEN:-}" && ( -z "${SHOPIFY_CLIENT_ID:-}" || -z "${SHOPIFY_CLIENT_SECRET:-}" ) ]]; then
      echo "  ✗ ENABLE_SHOPIFY=1 ma credenziali Shopify mancanti (CLIENT_ID+SECRET o ADMIN_TOKEN) — step saltato."
      FAILURES+=("shopify:no-creds")
    elif "$PY" pipeline/shopify_enricher.py --apply; then
      echo "  ✓ Shopify aggiornato"
    else
      echo "  ✗ Shopify enricher fallito"; FAILURES+=("shopify")
    fi
  else
    echo "  ⏭  Nessun merge valido in questa run — Shopify NON toccato."
  fi
else
  echo ""; echo "▷ [4/4] Shopify: step disattivato (ENABLE_SHOPIFY≠1) — salto."
fi

# ── Pulizia: tiene solo gli ultimi KEEP_DATA file per tipo ───────────────────
prune dati/carmodel carmodel_scraped
prune dati/mcws mcws_inventory
prune dati/merged merged_products
prune dati/scartati carmodel_scraped
prune dati/scartati mcws_inventory

# ── Riepilogo + notifica ─────────────────────────────────────────────────────
DURATA=$(( $(date +%s) - T_START ))
echo ""; echo "════════════════════════════════════════════════════════"
echo "RIEPILOGO  | carmodel: $(rows "$CARMODEL_CSV")  mcws: $(rows "$MCWS_CSV")  merged: $MERGED_ROWS  | $((DURATA / 60)) min"
echo "Log: $LOG_FILE"
echo "════════════════════════════════════════════════════════"

if (( ${#FAILURES[@]} == 0 )) && (( MERGED_ROWS > 0 )); then
  notify "Vroomi ✅ Inventario aggiornato" "merged: $MERGED_ROWS righe in $((DURATA / 60)) min"
  exit 0
else
  notify "Vroomi ⚠️ Inventario FALLITO" "step falliti: ${FAILURES[*]:-merge saltato}. Dati precedenti preservati."
  exit 1
fi
