"""
controller.py — logica del Pannello di Controllo Vroomi (usata da app.py / pipeline_ui.py).
Tutto portabile: i percorsi derivano dalla posizione di questo file, niente path fissi.

Funzioni: stato credenziali, interruttore arricchimento Shopify, lancio pipeline in
background + lettura log, gestione scheduling launchd (genera il plist per la macchina
corrente), ultimo risultato.
"""

from __future__ import annotations  # compatibilità Python 3.9 (sintassi "X | None")

import os
import re
import signal
import subprocess
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parent.parent
LOCAL_ENV = REPO / "credenziali.env"          # credenziali nella cartella (facile)
HOME_ENV = Path.home() / ".env.vroomi"        # oppure nella Home (setup di Matteo)


def env_file() -> Path:
    """File credenziali attivo: preferisce credenziali.env nella cartella (comodo
    per il collaboratore), altrimenti ~/.env.vroomi."""
    return LOCAL_ENV if LOCAL_ENV.exists() else HOME_ENV


RUN_SCRIPT = REPO / "pipeline" / "run.sh"
LOG_DIR = REPO / "logs"
RESULT_DIR = REPO / "RISULTATO"
LOCK_PID = LOG_DIR / ".run.lock" / "pid"       # scritto da run.sh finché la run è attiva

# Scheduling (launchd)
LAUNCH_LABEL = "com.vroomi.inventory"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"


# ─────────────────────────── Credenziali / .env ──────────────────────────────
def _read_env_text() -> str:
    f = env_file()
    return f.read_text(encoding="utf-8") if f.exists() else ""


def _env_value(key: str) -> str | None:
    """Legge un export KEY="..." dal file credenziali attivo (senza eseguirlo)."""
    m = re.search(rf'^\s*export\s+{re.escape(key)}=["\']?([^"\'\n]*)', _read_env_text(), re.M)
    return m.group(1) if m else None


def credentials_status() -> dict:
    """Quali credenziali sono presenti E compilate (mai i valori).
    NB: serve il valore non vuoto — il template ha le righe ma vuote."""
    def filled(key):
        return bool((_env_value(key) or "").strip())

    mcws = filled("MCWS_USERNAME") and filled("MCWS_PASSWORD")
    shopify = filled("SHOPIFY_ADMIN_TOKEN") or (
        filled("SHOPIFY_CLIENT_ID") and filled("SHOPIFY_CLIENT_SECRET"))
    return {
        "env_file": str(env_file()),
        "env_exists": env_file().exists(),
        "local_env": str(LOCAL_ENV),
        "local_env_exists": LOCAL_ENV.exists(),
        "template_exists": (REPO / "credenziali.esempio.env").exists(),
        "mcws": mcws,
        "shopify": shopify,
        "enable_shopify": (_env_value("ENABLE_SHOPIFY") or "0") == "1",
    }


def create_local_env_from_template() -> bool:
    """Crea credenziali.env copiando il template (se non esiste già).
    Ritorna True se creato ora."""
    template = REPO / "credenziali.esempio.env"
    if LOCAL_ENV.exists() or not template.exists():
        return False
    LOCAL_ENV.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        LOCAL_ENV.chmod(0o600)
    except OSError:
        pass
    return True


def set_enable_shopify(on: bool) -> None:
    """Imposta/aggiorna export ENABLE_SHOPIFY=0/1 nel file credenziali attivo."""
    val = "1" if on else "0"
    line = f'export ENABLE_SHOPIFY={val}'
    txt = _read_env_text()
    if re.search(r'^\s*export\s+ENABLE_SHOPIFY=', txt, re.M):
        txt = re.sub(r'^\s*export\s+ENABLE_SHOPIFY=.*$', line, txt, flags=re.M)
    else:
        if txt and not txt.endswith("\n"):
            txt += "\n"
        txt += line + "\n"
    f = env_file()
    f.write_text(txt, encoding="utf-8")
    try:
        f.chmod(0o600)
    except OSError:
        pass


# ─────────────────────────── Pipeline in background ───────────────────────────
def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)        # segnale 0 = test esistenza processo
        return True
    except OSError:
        return False


def running_pid() -> int | None:
    """PID della run in corso (avviata da pannello, pulsante o pianificazione)."""
    try:
        pid = int(LOCK_PID.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if _pid_alive(pid) else None


def is_running() -> bool:
    return running_pid() is not None


def current_logfile() -> Path | None:
    """Log della run più recente (in corso o conclusa)."""
    logs = sorted(LOG_DIR.glob("run_*.log"), key=lambda p: p.stat().st_mtime)
    return logs[-1] if logs else None


def start_pipeline(enable_shopify: bool | None = None) -> Path:
    """Lancia run.sh in background (sopravvive alla chiusura del browser).
    Ritorna il path del logfile. Se enable_shopify è passato, lo forza per QUESTA run."""
    if is_running():
        raise RuntimeError("Una run è già in corso.")
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")

    env = os.environ.copy()
    env["RUN_TIMESTAMP"] = ts                 # run.sh scrive logs/run_<ts>.log
    if enable_shopify is not None:
        env["ENABLE_SHOPIFY"] = "1" if enable_shopify else "0"

    # Avvio detached: nuovo gruppo di processi così non muore col padre (Streamlit).
    subprocess.Popen(
        ["/bin/bash", str(RUN_SCRIPT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=str(REPO), env=env, start_new_session=True,
    )
    return LOG_DIR / f"run_{ts}.log"


def stop_pipeline() -> bool:
    """Ferma la run in corso (termina l'intero gruppo di processi)."""
    pid = running_pid()
    if not pid:
        return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        return True
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False


# ─────────────────────────── Newsletter MCWS → Shopify ─────────────────────────
NEWSLETTER_SCRIPT = REPO / "pipeline" / "newsletter.sh"
NEWSLETTER_STATE = LOG_DIR / ".newsletter_run"      # "<pid> <logfile>" dell'ultima run


def start_newsletter(index: int, apply: bool) -> Path:
    """Lancia la newsletter n. <index> in background: prova (apply=False) o
    creazione dei prodotti in BOZZA su Shopify (apply=True). Ritorna il log."""
    if newsletter_running():
        raise RuntimeError("Un'importazione newsletter è già in corso.")
    LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    env = os.environ.copy()
    env["RUN_TIMESTAMP"] = ts
    args = ["/bin/bash", str(NEWSLETTER_SCRIPT), "--index", str(index)] + (["--apply"] if apply else [])
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            cwd=str(REPO), env=env, start_new_session=True)
    logfile = LOG_DIR / f"newsletter_{ts}.log"
    NEWSLETTER_STATE.write_text(f"{proc.pid} {logfile}", encoding="utf-8")
    return logfile


def _newsletter_state() -> tuple[int | None, Path | None]:
    try:
        pid, log = NEWSLETTER_STATE.read_text(encoding="utf-8").split(" ", 1)
        return int(pid), Path(log)
    except (OSError, ValueError):
        return None, None


def newsletter_running() -> bool:
    pid, _ = _newsletter_state()
    return bool(pid) and _pid_alive(pid)


def newsletter_logfile() -> Path | None:
    return _newsletter_state()[1]


def tail_log(path: Path | None, n: int = 200) -> str:
    if not path or not Path(path).exists():
        return ""
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


# ─────────────────────────── Ultimo risultato ────────────────────────────────
def latest_result() -> dict | None:
    f = RESULT_DIR / "merged_products_LATEST.csv"
    if not f.exists():
        cands = sorted(RESULT_DIR.glob("merged_products_*.csv"),
                       key=lambda p: p.stat().st_mtime) if RESULT_DIR.exists() else []
        if not cands:
            return None
        f = cands[-1]
    rows = max(0, sum(1 for _ in f.open(encoding="utf-8", errors="replace")) - 1)
    return {"path": f, "name": f.name, "rows": rows,
            "mtime": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}


# ─────────────────────────── Scheduling (launchd) ─────────────────────────────
def _uid() -> int:
    return os.getuid()


def plist_content() -> str:
    """Genera il plist per la macchina corrente: percorsi e shell giusti, ogni 2 giorni 07:00."""
    days = "".join(
        f"    <dict><key>Day</key><integer>{d}</integer>"
        f"<key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>\n"
        for d in range(1, 32, 2)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LAUNCH_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>{RUN_SCRIPT}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>{Path.home()}</string>
  </dict>
  <key>StartCalendarInterval</key>
  <array>
{days}  </array>
  <key>StandardOutPath</key><string>{LOG_DIR}/launchd.log</string>
  <key>StandardErrorPath</key><string>{LOG_DIR}/launchd.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
"""


def schedule_status() -> str:
    """Ritorna 'attivo', 'sospeso' o 'assente'."""
    if not PLIST_PATH.exists():
        return "assente"
    r = subprocess.run(["launchctl", "print", f"gui/{_uid()}/{LAUNCH_LABEL}"],
                       capture_output=True, text=True)
    return "attivo" if r.returncode == 0 else "sospeso"


def schedule_enable() -> tuple[bool, str]:
    """Genera/installa il plist e attiva la pianificazione per questa macchina."""
    try:
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLIST_PATH.write_text(plist_content(), encoding="utf-8")
        uid = _uid()
        subprocess.run(["launchctl", "enable", f"gui/{uid}/{LAUNCH_LABEL}"],
                       capture_output=True, text=True)
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LAUNCH_LABEL}"],
                       capture_output=True, text=True)  # idempotente
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
                           capture_output=True, text=True)
        ok = schedule_status() == "attivo"
        return ok, (r.stderr or r.stdout or "").strip()
    except Exception as e:
        return False, str(e)


def schedule_disable() -> tuple[bool, str]:
    """Disattiva la pianificazione in modo persistente (sopravvive ai riavvii)."""
    try:
        uid = _uid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LAUNCH_LABEL}"],
                       capture_output=True, text=True)
        subprocess.run(["launchctl", "disable", f"gui/{uid}/{LAUNCH_LABEL}"],
                       capture_output=True, text=True)
        ok = schedule_status() != "attivo"
        return ok, ""
    except Exception as e:
        return False, str(e)
