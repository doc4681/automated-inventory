#!/usr/bin/env bash
# run_local.sh — pipeline NON-INTERATTIVA per esecuzione automatica (launchd).
# Hardened per run unattended:
#   • guard anti-perdita-dati: una scrape/download fallita o sospetta NON sovrascrive
#     i dati buoni (il file scartato viene spostato in output/rejected/ e il merge saltato)
#   • log rotation: un log per run in logs/run_<ts>.log, conserva gli ultimi KEEP_LOGS
#   • notifiche: notifica macOS + webhook opzionale (Slack/Discord) su esito/fallimento
#   • headless opzionale via env CARMODEL_HEADLESS / MCWS_HEADLESS
#
# Eseguibile sia da launchd sia a mano:  bash run_local.sh
# Credenziali da ~/.env.vroomi. Webhook opzionale: export NOTIFY_WEBHOOK="https://..."

set -uo pipefail

# Percorso del repo ricavato da DOVE si trova questo script (portabile su qualsiasi Mac).
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO" || { echo "ERRORE: $REPO non trovato"; exit 1; }

# ── Soglie di validazione (override via env) ─────────────────────────────────
MIN_CARMODEL_ROWS="${MIN_CARMODEL_ROWS:-200}"   # min righe attese dallo scraper
MIN_MCWS_ROWS="${MIN_MCWS_ROWS:-1000}"          # min righe attese dall'inventario MCWS
MAX_DROP_PCT="${MAX_DROP_PCT:-50}"              # calo % max tollerato vs run precedente
MIN_BRAND_COVERAGE="${MIN_BRAND_COVERAGE:-90}"  # % min di brand attesi presenti nello scrape
KEEP_LOGS="${KEEP_LOGS:-20}"                    # n. di log per-run da conservare

# ── Credenziali ──────────────────────────────────────────────────────────────
# Sorgenti: ~/.env.vroomi (setup di Matteo) e/o credenziali.env nella cartella
# (comodo per il collaboratore). Se presenti entrambi, la cartella ha priorità.
if [[ -f "$HOME/.env.vroomi" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.env.vroomi"
fi
if [[ -f "$REPO/credenziali.env" ]]; then
  # shellcheck disable=SC1091
  source "$REPO/credenziali.env"
fi
if [[ -z "${MCWS_USERNAME:-}" || -z "${MCWS_PASSWORD:-}" ]]; then
  echo "ERRORE: credenziali MCWS mancanti. Compila 'credenziali.env' nella cartella"
  echo "        (oppure ~/.env.vroomi) con MCWS_USERNAME e MCWS_PASSWORD."
  exit 1
fi

# ── Python: virtualenv del repo se presente ──────────────────────────────────
if [[ -x "$REPO/.venv/bin/python" ]]; then PY="$REPO/.venv/bin/python"; else PY="$(command -v python3)"; fi

# ── Logging per-run + rotation ───────────────────────────────────────────────
export RUN_TIMESTAMP; RUN_TIMESTAMP="$(date '+%Y-%m-%d_%H%M')"
LOG_DIR="$REPO/logs"; mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_${RUN_TIMESTAMP}.log"
# Tutto su stdout (catturato dal plist in run_local.log = ultimo run) E su log per-run
exec > >(tee -a "$LOG_FILE") 2>&1
# Conserva solo gli ultimi KEEP_LOGS log
ls -1t "$LOG_DIR"/run_*.log 2>/dev/null | tail -n +$((KEEP_LOGS + 1)) | xargs -I{} rm -f {} 2>/dev/null || true

# ── Impedisce il sleep del Mac per tutta la durata ───────────────────────────
caffeinate -dims & CAFFEINATE_PID=$!
trap 'kill $CAFFEINATE_PID 2>/dev/null' EXIT

# ── Helpers ──────────────────────────────────────────────────────────────────
rows() { [[ -f "$1" ]] && { local n; n=$(tail -n +2 "$1" 2>/dev/null | wc -l | tr -d ' '); echo "${n:-0}"; } || echo 0; }

prev_file() {  # file piu' recente con quel prefisso, ESCLUSO il run corrente
  ls -1t "$1"/${2}_*.csv 2>/dev/null | grep -v "_${RUN_TIMESTAMP}.csv" | head -1
}

notify() {  # notify <titolo> <messaggio>
  /usr/bin/osascript -e "display notification \"$2\" with title \"$1\"" 2>/dev/null || true
  if [[ -n "${NOTIFY_WEBHOOK:-}" ]]; then
    curl -s -m 10 -X POST -H 'Content-Type: application/json' \
      -d "{\"text\":\"$1 — $2\"}" "$NOTIFY_WEBHOOK" >/dev/null 2>&1 || true
  fi
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

reject() {  # sposta il file sospetto in output/rejected/ così non viene riusato dal merger
  local f="$1" dir; dir="$(dirname "$f")/rejected"; mkdir -p "$dir"
  [[ -f "$f" ]] && mv "$f" "$dir/" && echo "  → spostato in $dir/"
}

# brand_coverage_ok <scraped_csv> → 0 se la copertura brand è sufficiente, 1 altrimenti
brand_coverage_ok() {
  "$PY" - "$1" "$REPO/Valid_Trademarks.txt" "$MIN_BRAND_COVERAGE" <<'PY'
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
      + (f" — mancanti: {', '.join(missing[:12])}{'…' if len(missing) > 12 else ''}" if cov < minpct else ""))
sys.exit(0 if cov >= minpct else 1)
PY
}

echo "════════════════════════════════════════════════════════"
echo "VROOMI — AGGIORNAMENTO INVENTARIO (auto)"
echo "Avvio: $(date '+%A %d %B %Y  %H:%M:%S')  |  Python: $PY  |  ts: $RUN_TIMESTAMP"
echo "════════════════════════════════════════════════════════"
T_START=$(date +%s)
FAILURES=()

CARMODEL_CSV="scraper/output/carmodel_scraped_${RUN_TIMESTAMP}.csv"
MCWS_CSV="downloader/output/mcws_inventory_${RUN_TIMESTAMP}.csv"
MERGED_CSV="merger/output/merged_products_${RUN_TIMESTAMP}.csv"

# ── STEP 1: Scraper carmodel.com ─────────────────────────────────────────────
echo ""; echo "▶ [1/3] Scraping carmodel.com..."
"$PY" scraper/carmodel_scraper.py || echo "  (scraper uscito con errore)"
CARMODEL_OK=1
if ! validate "$CARMODEL_CSV" "$MIN_CARMODEL_ROWS" "carmodel"; then
  CARMODEL_OK=0; FAILURES+=("scraper"); reject "$CARMODEL_CSV"
elif ! brand_coverage_ok "$CARMODEL_CSV"; then
  # scrape parziale (troppi brand mancanti, es. Chrome morto a inizio run) → scarta
  CARMODEL_OK=0; FAILURES+=("scraper:copertura"); reject "$CARMODEL_CSV"
fi

# ── STEP 2: Download MCWS ────────────────────────────────────────────────────
echo ""; echo "▶ [2/3] Download inventario MCWS..."
"$PY" downloader/mcws_downloader.py || echo "  (downloader uscito con errore)"
MCWS_OK=1
if ! validate "$MCWS_CSV" "$MIN_MCWS_ROWS" "mcws"; then
  MCWS_OK=0; FAILURES+=("downloader"); reject "$MCWS_CSV"
fi

# ── STEP 3: Merger (solo se entrambi gli input sono validi) ───────────────────
echo ""; echo "▶ [3/3] Merge dei cataloghi..."
MERGED_ROWS=0
if (( CARMODEL_OK == 1 && MCWS_OK == 1 )); then
  if "$PY" merger/product_merger.py; then
    MERGED_ROWS=$(rows "$MERGED_CSV")
    # Copia il risultato in RISULTATO/ con DUE nomi:
    #  • timestamped  → backup distinguibile per ogni run
    #  • _LATEST      → comodo puntatore all'ultimo (sempre il più recente)
    if (( MERGED_ROWS > 0 )); then
      mkdir -p "$REPO/RISULTATO"
      cp "$MERGED_CSV" "$REPO/RISULTATO/merged_products_${RUN_TIMESTAMP}.csv"
      cp "$MERGED_CSV" "$REPO/RISULTATO/merged_products_LATEST.csv"
      echo "  ✓ risultato → RISULTATO/merged_products_${RUN_TIMESTAMP}.csv (+ _LATEST.csv)"
    fi
  else
    FAILURES+=("merger"); echo "  ✗ merger fallito"
  fi
else
  echo "  ⏭  Merge SALTATO: input non validi. Dati buoni precedenti PRESERVATI."
  echo "     (l'ultimo merged_products valido resta quello piu' recente in merger/output/)"
fi

# ── STEP 4 (OPZIONALE): Shopify — scrive note → metafield custom.notes ────────
# Attiva con  ENABLE_SHOPIFY=1  (in ~/.env.vroomi o nell'ambiente).
# Richiede SHOPIFY_ADMIN_TOKEN (e opz. SHOPIFY_STORE_DOMAIN).
if [[ "${ENABLE_SHOPIFY:-0}" == "1" ]]; then
  echo ""; echo "▶ [4/4] Shopify: aggiorno metafield custom.notes..."
  if (( MERGED_ROWS > 0 )); then
    if [[ -z "${SHOPIFY_ADMIN_TOKEN:-}" && ( -z "${SHOPIFY_CLIENT_ID:-}" || -z "${SHOPIFY_CLIENT_SECRET:-}" ) ]]; then
      echo "  ✗ ENABLE_SHOPIFY=1 ma credenziali Shopify mancanti (CLIENT_ID+SECRET o ADMIN_TOKEN) — step saltato."
      FAILURES+=("shopify:no-creds")
    elif "$PY" shopify_enricher/shopify_enricher.py --apply; then
      echo "  ✓ Shopify aggiornato"
    else
      echo "  ✗ Shopify enricher fallito"; FAILURES+=("shopify")
    fi
  else
    echo "  ⏭  Nessun merge valido in questa run — Shopify NON toccato."
  fi
else
  echo ""; echo "▷ [4/4] Shopify: step DISATTIVATO (ENABLE_SHOPIFY≠1) — salto."
fi

# ── Riepilogo + notifica ─────────────────────────────────────────────────────
DURATA=$(( $(date +%s) - T_START ))
echo ""; echo "════════════════════════════════════════════════════════"
echo "RIEPILOGO  | carmodel: $(rows "$CARMODEL_CSV")  mcws: $(rows "$MCWS_CSV")  merged: $MERGED_ROWS  | ${DURATA}s"
echo "Log: $LOG_FILE"
echo "════════════════════════════════════════════════════════"

if (( ${#FAILURES[@]} == 0 )) && (( MERGED_ROWS > 0 )); then
  notify "Vroomi ✅ Inventario aggiornato" "merged: $MERGED_ROWS righe in ${DURATA}s"
  exit 0
else
  notify "Vroomi ⚠️ Inventario FALLITO" "step falliti: ${FAILURES[*]:-merge saltato}. Dati precedenti preservati."
  exit 1
fi
