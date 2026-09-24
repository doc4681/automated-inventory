# shellcheck shell=bash
# ════════════════════════════════════════════════════════════════════
#  Preparazione comune ai 3 script .command (NON va lanciato da solo:
#  viene letto con `source` da ciascun .command).
#
#  - trova un Python >= 3.10 (selenium/requests non supportano versioni
#    più vecchie: il python3 "di sistema" del Mac è spesso il 3.9);
#  - crea/ripara l'ambiente .venv: la verifica NON si basa sull'esistenza
#    della cartella ma sull'import reale dei moduli (un'installazione
#    interrotta o un venv Python 3.12+ senza setuptools/distutils
#    facevano crashare il programma subito, in silenzio);
#  - controlla credenziali e Chrome;
#  - fornisce `esegui_run` che lancia run.py e riporta l'esito VERO.
# ════════════════════════════════════════════════════════════════════

chiudi_con_errore() {
  echo ""
  echo "❌ $1"
  [[ -n "$2" ]] && echo "   $2"
  echo ""
  read -rp "Premi Invio per chiudere…" _
  exit 1
}

trova_python() {
  local c
  for c in python3.13 python3.12 python3.11 python3.10 \
           /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$c" >/dev/null 2>&1 &&
       "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      command -v "$c"
      return 0
    fi
  done
  return 1
}

dipendenze_ok() {
  [[ -x ".venv/bin/python" ]] &&
    ./.venv/bin/python -c "import undetected_chromedriver, selenium, bs4, requests" >/dev/null 2>&1
}

prepara_ambiente() {
  if dipendenze_ok; then
    return 0
  fi

  local py
  if ! py=$(trova_python); then
    local attuale
    attuale=$(python3 --version 2>/dev/null || echo "nessun Python 3 trovato")
    chiudi_con_errore "Serve Python 3.10 o più recente (trovato: $attuale)." \
      "Installalo da https://www.python.org/downloads/ (pulsante giallo) e riprova."
  fi

  if [[ -d ".venv" ]]; then
    echo "▶ L'ambiente esistente è incompleto o danneggiato: lo ricreo (1-2 minuti)…"
    rm -rf .venv
  else
    echo "▶ Primo avvio: preparo l'ambiente (1-2 minuti)…"
  fi
  echo "  (uso $("$py" --version 2>&1))"

  "$py" -m venv .venv || chiudi_con_errore "Impossibile creare l'ambiente Python (.venv)."
  ./.venv/bin/python -m pip install --upgrade pip >/dev/null 2>&1
  echo "▶ Installo le dipendenze…"
  ./.venv/bin/python -m pip install -r requirements.txt ||
    chiudi_con_errore "Errore nell'installazione delle dipendenze." \
      "Controlla la connessione a internet e riprova."

  dipendenze_ok || chiudi_con_errore "Le dipendenze risultano installate ma non si caricano." \
    "Manda a Matteo il testo qui sopra."
  echo "✅ Ambiente pronto."
  echo ""
}

controlla_credenziali() {
  if [[ ! -f "credenziali.env" ]]; then
    chiudi_con_errore "Manca il file  credenziali.env  in questa cartella." \
      "Copia credenziali.esempio.env in credenziali.env e compilalo (o chiedilo a Matteo)."
  fi
  if grep -q "tua-email@esempio.com" credenziali.env 2>/dev/null; then
    chiudi_con_errore "Devi ancora inserire le credenziali." \
      "Apri il file  credenziali.env  con TextEdit, compila e salva."
  fi
}

controlla_chrome() {
  if [[ ! -d "/Applications/Google Chrome.app" && ! -d "$HOME/Applications/Google Chrome.app" ]]; then
    chiudi_con_errore "Google Chrome non trovato nella cartella Applicazioni." \
      "Installalo da https://www.google.com/chrome/ e riprova."
  fi
}

# Lancia run.py con gli argomenti dati e salva l'esito in ESITO_RUN.
# L'output va sia a schermo sia in output/ultima_run.log (utile da mandare
# a Matteo se qualcosa va storto).
esegui_run() {
  mkdir -p output
  ./.venv/bin/python -u run.py "$@" 2>&1 | tee output/ultima_run.log
  ESITO_RUN=${PIPESTATUS[0]}
}

prepara_tutto() {
  prepara_ambiente
  controlla_credenziali
  controlla_chrome
}
