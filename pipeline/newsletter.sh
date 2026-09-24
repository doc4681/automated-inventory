#!/usr/bin/env bash
# newsletter.sh — lancia pipeline/mcws_newsletter.py con le credenziali caricate
# e un log in logs/newsletter_<ts>.log. Argomenti passati così come sono, es.:
#   bash pipeline/newsletter.sh --index 1            # prova, non scrive nulla
#   bash pipeline/newsletter.sh --index 1 --apply    # crea i prodotti in BOZZA

set -uo pipefail
PIPE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$PIPE")"
cd "$REPO" || exit 1

export RUN_TIMESTAMP="${RUN_TIMESTAMP:-$(date '+%Y-%m-%d_%H%M')}"
export PYTHONUNBUFFERED=1
mkdir -p logs
exec > >(tee -a "logs/newsletter_${RUN_TIMESTAMP}.log") 2>&1

# shellcheck disable=SC1091
[[ -f "$HOME/.env.vroomi" ]] && source "$HOME/.env.vroomi"
# shellcheck disable=SC1091
[[ -f "$REPO/credenziali.env" ]] && source "$REPO/credenziali.env"
if [[ -x "$REPO/.venv/bin/python" ]]; then PY="$REPO/.venv/bin/python"; else PY="$(command -v python3)"; fi

"$PY" pipeline/mcws_newsletter.py "$@"
