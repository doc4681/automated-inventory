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

# ── Primo avvio: crea l'ambiente Python e installa le dipendenze ─────────────
if [[ ! -x ".venv/bin/python" ]]; then
  echo "▶ Primo avvio: preparo l'ambiente (1-2 minuti)…"
  if ! python3 -m venv .venv; then
    echo "❌ Errore nella creazione dell'ambiente. Python 3 è installato?"
    read -rp "Premi Invio per chiudere…" _; exit 1
  fi
  ./.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
  echo "▶ Installo le dipendenze…"
  if ! ./.venv/bin/python -m pip install -r requirements.txt; then
    echo "❌ Errore nell'installazione delle dipendenze."
    read -rp "Premi Invio per chiudere…" _; exit 1
  fi
fi

# ── Verifica che streamlit ci sia (es. dopo un aggiornamento dei requisiti) ──
if ! ./.venv/bin/python -c "import streamlit" 2>/dev/null; then
  echo "▶ Aggiorno le dipendenze…"
  ./.venv/bin/python -m pip install -r requirements.txt
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

exec ./.venv/bin/python -m streamlit run app.py
