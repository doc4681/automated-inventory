"""
aggiornamenti.py — il pannello si tiene aggiornato da solo.

  • una volta al giorno chiede a GitHub qual è l'ultima versione del programma (l'ultimo
    commit del ramo che scarica installa.sh, di solito main) e la confronta con quella
    installata, scritta da installa.sh nel file .versione;
  • se sono diverse il pannello mostra l'avviso «È disponibile un aggiornamento»
    (pannello/aggiornamenti_ui.py);
  • «Aggiorna adesso» lancia questo file in background: rilancia installa.sh (la stessa
    riga del LEGGIMI: password, dati, RISULTATO, logs e .venv restano), reinstalla le
    dipendenze se sono cambiate, chiude il pannello e lo riapre (AVVIA PANNELLO.command).
    Se l'installazione fallisce il pannello resta aperto com'era e mostra l'errore.

Le copie scaricate con git (cartella .git) non vengono toccate: si aggiornano con git pull.

Da Terminale (dalla cartella principale):
  .venv/bin/python -m pannello.aggiornamenti           # controlla adesso
  .venv/bin/python -m pannello.aggiornamenti --esegui  # aggiorna (senza riaprire il pannello)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
GITHUB_REPO = "doc4681/automated-inventory"
API = f"https://api.github.com/repos/{GITHUB_REPO}"
VERSION_FILE = REPO / ".versione"                 # scritto da installa.sh
STATE_FILE = REPO / "dati" / "aggiornamenti.json"  # ultimo controllo, aggiornamento in corso
LOG_DIR = REPO / "logs"
LAUNCHER = REPO / "AVVIA PANNELLO.command"

CHECK_EVERY = timedelta(hours=24)   # un controllo al giorno
RETRY_AFTER = timedelta(hours=1)    # se GitHub non risponde, riprova dopo un'ora
MAX_NEWS = 8                        # righe di «Cosa cambia» mostrate nel pannello
TIMEOUT = 5                         # secondi: se GitHub non risponde il pannello non resta fermo

_SHA = re.compile(r"^[0-9a-f]{40}$")


def log(msg: str = "") -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}" if msg else "", flush=True)


# ─────────────────────────── Versione e stato ────────────────────────────────
def is_dev_copy() -> bool:
    """Copia scaricata con git: si aggiorna con git pull, non da qui."""
    return (REPO / ".git").exists()


def local_version() -> tuple[str | None, str]:
    """(commit installato, ramo) da .versione. Commit None = sconosciuto
    (installazione precedente a questa funzione)."""
    try:
        lines = VERSION_FILE.read_text(encoding="utf-8").split()
    except OSError:
        return None, "main"
    sha = lines[0] if lines and _SHA.match(lines[0]) else None
    return sha, (lines[1] if len(lines) > 1 else "main")


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _update_state(**changes) -> dict:
    state = _load_state()
    state.update(changes)
    _save_state(state)
    return state


def _dt(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _pid_alive(pid) -> bool:
    from pannello.controller import _pid_alive as alive
    try:
        return bool(pid) and alive(int(pid))
    except (TypeError, ValueError):
        return False


# ─────────────────────────── Controllo su GitHub ─────────────────────────────
def _get(url: str) -> dict:
    r = requests.get(url, timeout=TIMEOUT, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "vroomi-pannello"})
    r.raise_for_status()
    return r.json()


def _news(local: str, remote: str) -> list[str]:
    """Titoli dei cambiamenti tra la versione installata e l'ultima (più recenti
    prima). Le «Merge pull request …» si saltano: i commit che contengono ci sono già."""
    data = _get(f"{API}/compare/{local}...{remote}")
    titles: list[str] = []
    for c in reversed(data.get("commits", [])):
        first = (c.get("commit", {}).get("message") or "").strip().splitlines()
        title = first[0].strip() if first else ""
        if title and not title.startswith("Merge ") and title not in titles:
            titles.append(title)
    return titles[:MAX_NEWS]


def check(force: bool = False) -> dict:
    """Chiede a GitHub l'ultima versione, al massimo una volta al giorno (force=True:
    subito). Ritorna lo stato salvato in dati/aggiornamenti.json."""
    state = _load_state()
    now = datetime.now()
    last_ok, last_try = _dt(state.get("controllato")), _dt(state.get("tentativo"))
    local, ref = local_version()
    if not force and state.get("ramo") == ref:
        if last_ok and now - last_ok < CHECK_EVERY:
            return state
        if last_try and now - last_try < RETRY_AFTER:
            return state
    state["tentativo"] = now.isoformat(timespec="seconds")
    try:
        head = _get(f"{API}/commits/{ref}")
        remote = head["sha"]
        news: list[str] = []
        if local and local != remote:
            try:
                news = _news(local, remote)
            except (requests.RequestException, ValueError, KeyError):
                pass                       # «cosa cambia» è solo un di più
        state.update(controllato=now.isoformat(timespec="seconds"), ramo=ref, remoto=remote,
                     data_remota=head.get("commit", {}).get("committer", {}).get("date"),
                     novita=news, errore=None)
    except (requests.RequestException, ValueError, KeyError) as e:
        state["errore"] = f"{type(e).__name__}: {e}"
    _save_state(state)
    return state


def status(force: bool = False) -> dict:
    """Tutto quello che serve al pannello per decidere se mostrare l'avviso."""
    state = check(force)
    local, ref = local_version()
    remote = state.get("remoto") if state.get("ramo") == ref else None
    published = _dt((state.get("data_remota") or "").replace("Z", "+00:00"))
    return {
        "locale": local,
        "ramo": ref,
        "remoto": remote,
        # versione installata sconosciuta = installata prima di questa funzione: meglio aggiornare
        "serve": bool(remote) and remote != local,
        "pubblicata": published.astimezone().replace(tzinfo=None) if published else None,
        "novita": state.get("novita") or [],
        "controllato": _dt(state.get("controllato")),
        "errore_controllo": state.get("errore"),
        "in_corso": _pid_alive(state.get("in_corso_pid")),
        "errore_aggiornamento": state.get("errore_aggiornamento"),
        "log": state.get("log"),
        "aggiornato_il": _dt(state.get("aggiornato_il")),
    }


def busy_reason() -> str:
    """Un lavoro che usa i file del programma è in corso: meglio non aggiornare adesso."""
    from pannello import controller as ctl
    if ctl.is_running():
        return "l'aggiornamento del catalogo fornitori è in corso"
    if ctl.newsletter_running():
        return "la creazione dei prodotti dalle newsletter è in corso"
    if ctl.inventory_running():
        return "l'aggiornamento dell'inventario è in corso"
    return ""


# ─────────────────────────── Aggiornamento ───────────────────────────────────
def start_update() -> Path:
    """Lancia l'aggiornamento in background (sopravvive alla chiusura del pannello)
    e gli passa il PID del pannello, che verrà chiuso e riaperto."""
    if status()["in_corso"]:
        raise RuntimeError("Un aggiornamento è già in corso.")
    LOG_DIR.mkdir(exist_ok=True)
    logfile = LOG_DIR / f"aggiornamento_{datetime.now():%Y-%m-%d_%H%M%S}.log"
    with open(logfile, "w", encoding="utf-8") as lf:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pannello.aggiornamenti", "--esegui",
             "--riavvia", str(os.getpid())],
            stdout=lf, stderr=subprocess.STDOUT, cwd=str(REPO), start_new_session=True)
    _update_state(in_corso_pid=proc.pid, errore_aggiornamento=None, log=str(logfile))
    return logfile


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _install() -> None:
    """Scarica e lancia l'ultimo installa.sh (come la riga del LEGGIMI) su questa cartella.
    Lo script arriva da GitHub e passa a bash in memoria: la copia nella cartella viene
    sostituita mentre gira, eseguirla da lì la rovinerebbe."""
    _local, ref = local_version()
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{ref}/installa.sh"
    log(f"▶ Scarico il programma di installazione ({ref})…")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    if not r.text.startswith("#!"):
        raise RuntimeError("installa.sh scaricato non valido")
    env = {**os.environ, "VROOMI_NO_OPEN": "1", "VROOMI_REF": ref}
    res = subprocess.run(["bash", "-s", "--", str(REPO)], input=r.text, text=True, env=env)
    if res.returncode != 0:
        raise RuntimeError(f"installa.sh è terminato con errore (codice {res.returncode})")


def _close_panel(pid: int) -> None:
    """Chiude il pannello vecchio (il processo di Streamlit) e la sua finestra del Terminale."""
    tty = subprocess.run(["ps", "-o", "tty=", "-p", str(pid)],
                         capture_output=True, text=True).stdout.strip()
    log(f"▶ Chiudo il pannello (processo {pid})…")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(30):
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
        except OSError:
            break
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        time.sleep(1)
    # Finestra del Terminale rimasta aperta con «[Processo completato]»: la chiude se
    # contiene solo il pannello. Se non ci riesce resta lì, non è un problema.
    if tty and tty not in ("?", "??") and sys.platform == "darwin":
        script = f'''
tell application "Terminal"
  repeat with w in (get windows)
    try
      if (count of tabs of w) is 1 and tty of tab 1 of w is "/dev/{tty}" then
        close w
        exit repeat
      end if
    end try
  end repeat
end tell'''
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=20)


def _notify(text: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e",
                        f'display notification "{text}" with title "Vroomi"'],
                       capture_output=True)


def run_update(panel_pid: int | None) -> int:
    """Il lavoro vero (gira in background, lanciato da start_update)."""
    log("Aggiornamento del programma Vroomi")
    if is_dev_copy():
        log("✗ Copia scaricata con git: aggiornala con  git pull.")
        _update_state(in_corso_pid=None, errore_aggiornamento="copia git: usa git pull")
        return 1
    time.sleep(2)                       # lascia al pannello il tempo di mostrare l'avviso
    req = REPO / "requirements.txt"
    req_before = _file_hash(req)
    try:
        _install()
        if _file_hash(req) != req_before:
            log("▶ Sono cambiate le dipendenze: le reinstallo…")
            res = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)])
            if res.returncode != 0:
                log("⚠️ Reinstallazione non riuscita: ci riprova AVVIA PANNELLO.command.")
    except Exception as e:  # noqa: BLE001 — qualsiasi errore: il pannello resta com'era
        log(f"✗ Aggiornamento non riuscito: {e}")
        _update_state(in_corso_pid=None, errore_aggiornamento=str(e))
        _notify("Aggiornamento non riuscito: il pannello resta com'era.")
        return 1

    local, _ref = local_version()
    _update_state(in_corso_pid=None, errore_aggiornamento=None,
                  aggiornato_il=datetime.now().isoformat(timespec="seconds"),
                  remoto=local or _load_state().get("remoto"), novita=[])
    log(f"✓ Programma aggiornato (versione {(local or '?')[:7]}).")

    if panel_pid:
        _close_panel(panel_pid)
        if sys.platform == "darwin" and LAUNCHER.exists():
            log("▶ Riapro il pannello…")
            subprocess.run(["open", str(LAUNCHER)])
        _notify("Programma aggiornato: il pannello si sta riaprendo.")
    log("✓ Fatto.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Aggiornamenti del programma Vroomi")
    ap.add_argument("--esegui", action="store_true", help="aggiorna adesso")
    ap.add_argument("--riavvia", type=int, metavar="PID",
                    help="(uso interno) PID del pannello da chiudere e riaprire")
    args = ap.parse_args()
    if args.esegui:
        return run_update(args.riavvia)
    s = status(force=True)
    print(f"Installata: {s['locale'] or 'sconosciuta'}  (ramo {s['ramo']})")
    print(f"Ultima:     {s['remoto'] or '—'}")
    if s["errore_controllo"]:
        print(f"Controllo non riuscito: {s['errore_controllo']}")
    print("➡️  Aggiornamento disponibile." if s["serve"] else "✓ Sei all'ultima versione.")
    for n in s["novita"]:
        print(f"   • {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
