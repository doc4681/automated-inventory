#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  DOPPIO CLICK QUI per aprire il Pannello di Controllo Vroomi.
# ════════════════════════════════════════════════════════════════════
# Al primo avvio prepara da solo l'ambiente (1-2 minuti). Poi apre il
# pannello nel browser. Per chiudere: chiudi questa finestra del Terminale.

cd "$(dirname "$0")" || { echo "Cartella non trovata"; read -r; exit 1; }

clear
echo "╔══════════════════════════════════════════════╗"
echo "║       VROOMI — Pannello di Controllo          ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Python: serve il 3.10 o più recente (le newsletter non girano col 3.9,
#    che è il python3 "di sistema" di molti Mac) ───────────────────────────────
trova_python() {
  local c
  for c in python3.13 python3.12 python3.11 python3.10 \
           /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$c" >/dev/null 2>&1 &&
       "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      command -v "$c"; return 0
    fi
  done
  return 1
}
PY_OK=$(trova_python || true)

# Ambiente creato in passato con un Python troppo vecchio: lo ricrea (se c'è
# un Python adatto), così funzionano anche le newsletter.
if [[ -x ".venv/bin/python" && -n "$PY_OK" ]] &&
   ! ./.venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "▶ Aggiorno l'ambiente a un Python più recente (1-2 minuti)…"
  rm -rf .venv
fi

# ── Primo avvio: crea l'ambiente Python e installa le dipendenze ─────────────
if [[ ! -x ".venv/bin/python" ]]; then
  if [[ -z "$PY_OK" ]]; then
    echo "❌ Serve Python 3.10 o più recente (trovato: $(python3 --version 2>/dev/null || echo 'nessuno'))."
    echo "   Installalo da https://www.python.org/downloads/ (pulsante giallo) e riprova."
    read -rp "Premi Invio per chiudere…" _; exit 1
  fi
  echo "▶ Primo avvio: preparo l'ambiente (1-2 minuti)…"
  if ! "$PY_OK" -m venv .venv; then
    echo "❌ Errore nella creazione dell'ambiente Python."
    read -rp "Premi Invio per chiudere…" _; exit 1
  fi
  ./.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
  echo "▶ Installo le dipendenze…"
  if ! ./.venv/bin/python -m pip install -r requirements.txt; then
    echo "❌ Errore nell'installazione delle dipendenze. Controlla la connessione e riprova."
    read -rp "Premi Invio per chiudere…" _; exit 1
  fi
fi

# ── Verifica che ci sia tutto: pannello (streamlit ≥ 1.37), inventario e
#    newsletter/catalogo (Chrome automatico). Se manca qualcosa lo installa. ──
if ! ./.venv/bin/python -c "
import sys, streamlit as s, pandas, openpyxl, xlrd, requests, bs4, selenium, undetected_chromedriver
sys.exit(tuple(map(int, s.__version__.split('.')[:2])) < (1, 37))" 2>/dev/null; then
  echo "▶ Aggiorno le dipendenze…"
  ./.venv/bin/python -m pip install -r requirements.txt
fi

# ── Ripara i venv già esistenti creati con Python 3.12+ ─────────────────────
# In Python 3.12+ distutils è stato rimosso e i venv nuovi non hanno setuptools.
# undetected-chromedriver lo richiede: senza, scraper/downloader crashano
# ("No module named 'distutils'"). Reinstalliamo setuptools SENZA ricreare
# il venv (nessun dato perso), utile per chi ha già installato l'app.
if ! ./.venv/bin/python -c "import distutils" 2>/dev/null; then
  echo "▶ Installo un componente mancante (setuptools)…"
  ./.venv/bin/python -m pip install "setuptools>=68" >/dev/null 2>&1
fi

# ── Evita la domanda dell'email al primo avvio di Streamlit ─────────────────
# Senza questo, al primo avvio Streamlit chiede un'email nel Terminale e
# resta bloccato in attesa: il pannello non si apre.
mkdir -p "$HOME/.streamlit"
if [[ ! -f "$HOME/.streamlit/credentials.toml" ]]; then
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

echo ""
echo "✅ Apro il pannello nel browser… (lascia aperta questa finestra)"
echo "   Se non si apre da solo, vai su:  http://localhost:8501"
echo ""

# ── A ogni avvio: se su GitHub c'è una versione nuova la scarica (con notifica),
#    riparte da questo file aggiornato e poi apre il pannello (pannello/aggiornamenti.py).
#    «exec»: questo file può essere sostituito dall'aggiornamento senza problemi.
if ./.venv/bin/python -c "import pannello.aggiornamenti" 2>/dev/null; then
  exec ./.venv/bin/python -m pannello.aggiornamenti --avvio
fi
exec ./.venv/bin/python -m streamlit run app.py
