"""
controller.py — logica del Pannello di Controllo Vroomi (usata dalle pagine pannello/*_ui.py).
Tutto portabile: i percorsi derivano dalla posizione di questo file, niente path fissi.

Funzioni: stato credenziali, interruttore arricchimento Shopify, lancio pipeline in
background + lettura log, gestione scheduling launchd (genera il plist per la macchina
corrente), ultimo risultato.
"""

from __future__ import annotations  # compatibilità Python 3.9 (sintassi "X | None")

import json
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
MCWS_DIR = REPO / "dati" / "mcws"              # listini MCWS scaricati dalla pipeline
TRADEMARKS_FILE = REPO / "config" / "Valid_Trademarks.txt"
MARKUP_FILE = REPO / "config" / "Vroomi_Markup.txt"
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
    m = re.search(rf"""^\s*export\s+{re.escape(key)}=(?:'([^'\n]*)'|"([^"\n]*)"|([^\s#]*))""",
                  _read_env_text(), re.M)
    return next((g for g in m.groups() if g is not None), "").strip() if m else None


# Valori finti dei file di esempio: se sono ancora lì, la password non è stata inserita.
PLACEHOLDERS = {"tua-email@esempio.com"}


def credentials_status() -> dict:
    """Quali credenziali sono presenti E compilate (mai i valori).
    NB: serve il valore non vuoto — il template ha le righe ma vuote."""
    def filled(key):
        v = (_env_value(key) or "").strip()
        return bool(v) and v not in PLACEHOLDERS

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


def save_credentials(values: dict) -> None:
    """Scrive in credenziali.env i valori NON vuoti di values ({"MCWS_USERNAME": ...}).
    I campi lasciati vuoti restano com'erano. Valori tra virgolette singole (come
    chiede il template), quindi non possono contenere apostrofi o a capo."""
    for k, v in values.items():
        if "'" in v or "\n" in v:
            raise ValueError(f"{k}: il valore contiene un apostrofo o un a capo.")
    if not env_file().exists():
        create_local_env_from_template()
    f = env_file() if env_file().exists() else LOCAL_ENV
    txt = f.read_text(encoding="utf-8") if f.exists() else ""
    for k, v in values.items():
        if not v:
            continue
        line = f"export {k}='{v}'"
        pattern = rf'^\s*export\s+{re.escape(k)}=.*$'
        if re.search(pattern, txt, re.M):
            txt = re.sub(pattern, lambda _m: line, txt, count=1, flags=re.M)
        else:
            if txt and not txt.endswith("\n"):
                txt += "\n"
            txt += line + "\n"
    f.write_text(txt, encoding="utf-8")
    try:
        f.chmod(0o600)
    except OSError:
        pass


def env_value_set(key: str) -> str:
    """Valore corrente (solo per campi NON segreti, es. lo username MCWS)."""
    return (_env_value(key) or "").strip()


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
    # Un lavoro lanciato dal pannello (newsletter, inventario) è un processo figlio:
    # finito, resta "zombie" e kill(0) lo darebbe ancora vivo. Lo raccogliamo qui.
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except ChildProcessError:
        pass                   # non è un nostro figlio (es. run.sh della pianificazione)
    except OSError:
        return False
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
# Unico strumento: Vroomi-Newsletter/run.py (lo stesso dei 3 script per Giuliano).
NEWSLETTER_DIR = REPO / "Vroomi-Newsletter"
NEWSLETTER_STATE = LOG_DIR / ".newsletter_run"      # "<pid> <logfile>" dell'ultima run
NEWSLETTER_INFO = LOG_DIR / ".newsletter_info.json"  # modalità e ID dell'ultima run
CRED_KEYS = ("MCWS_USERNAME", "MCWS_PASSWORD", "SHOPIFY_STORE_DOMAIN",
             "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET", "SHOPIFY_ADMIN_TOKEN")


def start_newsletter(ids: str, apply: bool) -> Path:
    """Lancia Vroomi-Newsletter in background: ids = "15538" o "15538,15540"
    (vuoto = tutte le newsletter valide). apply=False → prova, True → bozze."""
    if newsletter_running():
        raise RuntimeError("Un'importazione newsletter è già in corso.")
    LOG_DIR.mkdir(exist_ok=True)
    logfile = LOG_DIR / f"newsletter_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.log"
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    for k in CRED_KEYS:                       # stesse credenziali della pipeline
        v = _env_value(k)
        if v:
            env[k] = v
    py = REPO / ".venv" / "bin" / "python"
    args = [str(py if py.exists() else "python3"), "-u", "run.py"]
    ids = re.sub(r"[^0-9,]", "", ids or "")
    if ids:
        args += ["--newsletter", ids]
    if apply:
        args.append("--apply")
    with open(logfile, "w") as lf:
        proc = subprocess.Popen(args, stdout=lf, stderr=subprocess.STDOUT,
                                cwd=str(NEWSLETTER_DIR), env=env, start_new_session=True)
    NEWSLETTER_STATE.write_text(f"{proc.pid} {logfile}", encoding="utf-8")
    NEWSLETTER_INFO.write_text(json.dumps({"apply": apply, "ids": ids}), encoding="utf-8")
    return logfile


def newsletter_info() -> dict:
    """{"apply": bool, "ids": "15538,…"} dell'ultima run (vuoto se sconosciuto)."""
    try:
        return json.loads(NEWSLETTER_INFO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def stop_newsletter() -> bool:
    pid, _ = _newsletter_state()
    if not pid or not _pid_alive(pid):
        return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        return True
    except OSError:
        return False


def _newsletter_state() -> tuple[int | None, Path | None]:
    try:
        pid, log = NEWSLETTER_STATE.read_text(encoding="utf-8").strip().split(" ", 1)
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


def newsletter_summary(path: Path | None) -> dict:
    """Riassunto leggibile di una run newsletter, ricavato dal suo log."""
    text = Path(path).read_text(encoding="utf-8", errors="replace") if path and Path(path).exists() else ""

    def num(label):
        m = re.search(rf"{re.escape(label)}\s*(\d+)", text)
        return int(m.group(1)) if m else 0

    report = re.search(r"^Report: (.+)$", text, re.M)
    errors = [l.strip() for l in text.splitlines() if l.strip().startswith("ERRORE")]
    skipped = re.search(r"^Scartate \(\d+\): (.+)$", text, re.M)
    return {
        "newsletters": num("Newsletter valide da elaborare:"),
        "none_found": "NESSUNA newsletter" in text,
        "skipped": skipped.group(1) if skipped else "",
        "created": num("creati:"),
        "existing": num("esistenti (saltati):"),
        "to_create": num("da creare (dry-run):"),
        "no_price": num("Prodotti senza prezzo (saltati):"),
        "create_errors": num("ERRORI in creazione su Shopify:"),
        "errors": errors,
        "report": Path(report.group(1).strip()) if report else None,
    }


# ─────────────────────────── Inventario automatico → Shopify ───────────────────
# pannello/inventario_sync.py: legge i prodotti da Shopify, li confronta con i
# listini (MCWS automatico, BBR ultimo caricato) e, se richiesto, applica le modifiche.
INVENTORY_STATE = LOG_DIR / ".inventario_run"        # "<pid> <logfile>" dell'ultima run
INVENTORY_INFO = LOG_DIR / ".inventario_info.json"   # opzioni dell'ultima run
BBR_DIR = REPO / "dati" / "bbr"                      # giacenze BBR caricate nel pannello
KEEP_BBR = 15


def start_inventory(prices_only: bool, apply: bool, mcws_fresh: bool = False,
                    mcws: str = "", bbr: str = "", use_bbr: bool = True,
                    force: bool = False) -> Path:
    """Lancia pannello/inventario_sync.py in background. apply=False → solo controllo."""
    if inventory_running():
        raise RuntimeError("Un aggiornamento dell'inventario è già in corso.")
    LOG_DIR.mkdir(exist_ok=True)
    logfile = LOG_DIR / f"inventario_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.log"
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    for k in CRED_KEYS:
        v = _env_value(k)
        if v:
            env[k] = v
    py = REPO / ".venv" / "bin" / "python"
    args = [str(py if py.exists() else "python3"), "-u", "-m", "pannello.inventario_sync"]
    if prices_only:
        args.append("--solo-prezzi")
    else:
        if mcws:
            args += ["--mcws", mcws]
        elif mcws_fresh:
            args.append("--mcws-nuovo")
        if not use_bbr:
            args.append("--senza-bbr")
        elif bbr:
            args += ["--bbr", bbr]
    if apply:
        args.append("--apply")
    if force:
        args.append("--forza")
    with open(logfile, "w") as lf:
        proc = subprocess.Popen(args, stdout=lf, stderr=subprocess.STDOUT,
                                cwd=str(REPO), env=env, start_new_session=True)
    INVENTORY_STATE.write_text(f"{proc.pid} {logfile}", encoding="utf-8")
    INVENTORY_INFO.write_text(json.dumps({"apply": apply, "prices_only": prices_only,
                                          "use_bbr": use_bbr}), encoding="utf-8")
    return logfile


def _inventory_state() -> tuple[int | None, Path | None]:
    try:
        pid, log = INVENTORY_STATE.read_text(encoding="utf-8").strip().split(" ", 1)
        return int(pid), Path(log)
    except (OSError, ValueError):
        return None, None


def inventory_running() -> bool:
    pid, _ = _inventory_state()
    return bool(pid) and _pid_alive(pid)


def inventory_logfile() -> Path | None:
    return _inventory_state()[1]


def inventory_info() -> dict:
    try:
        return json.loads(INVENTORY_INFO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def stop_inventory() -> bool:
    pid, _ = _inventory_state()
    if not pid or not _pid_alive(pid):
        return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        return True
    except OSError:
        return False


def inventory_summary(path: Path | None) -> dict:
    """Riassunto leggibile di una run dell'inventario, ricavato dal suo log."""
    text = Path(path).read_text(encoding="utf-8", errors="replace") if path and Path(path).exists() else ""

    def num(label):
        m = re.search(rf"{re.escape(label)}\s*(\d+)", text)
        return int(m.group(1)) if m else 0

    def line(label):
        m = re.search(rf"^{re.escape(label)}\s*(.+)$", text, re.M)
        return m.group(1).strip() if m else ""

    steps = re.findall(r"▶ \[(\d)/4\]", text)
    return {
        "step": int(steps[-1]) if steps else 0,
        "finished": "FINE" in text.splitlines()[-3:] if text else False,
        "read": num("Prodotti letti da Shopify:"),
        "to_update": num("Prodotti da aggiornare:"),
        "back": num("tornano disponibili:"),
        "out": num("diventano esauriti:"),
        "prices": num("prezzi cambiati:"),
        "costs": num("costi cambiati:"),
        "available": num("disponibili ora nel negozio:"),
        "applied": num("Aggiornati su Shopify:"),
        "apply_errors": num("Errori su Shopify:"),
        "applied_done": "Aggiornati su Shopify:" in text,
        "too_many": "TROPPI ESAURITI" in text,
        "blocked": "BLOCCATO" in text,
        "mcws_fallback": "ATTENZIONE: uso l'ultimo listino" in text,
        "mcws_file": line("File MCWS usato:"),
        "bbr_file": line("File BBR usato:"),
        "mcws_line": line("Listino MCWS:"),
        "bbr_line": line("Giacenze BBR:"),
        "errors": [l.strip() for l in text.splitlines() if l.strip().startswith("ERRORE")],
        "report": Path(line("Report:")) if line("Report:") else None,
    }


def latest_bbr() -> dict | None:
    """L'ultimo file di giacenze BBR caricato nel pannello."""
    files = sorted(BBR_DIR.glob("bbr_giacenze_*"), key=lambda p: p.stat().st_mtime) \
        if BBR_DIR.exists() else []
    if not files:
        return None
    return {"path": files[-1], "mtime": datetime.fromtimestamp(files[-1].stat().st_mtime)}


def save_bbr(filename: str, data: bytes) -> Path:
    """Salva le giacenze BBR caricate, così la prossima volta non serve ricaricarle."""
    BBR_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower() or ".csv"
    dest = BBR_DIR / f"bbr_giacenze_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}{ext}"
    dest.write_bytes(data)
    for old in sorted(BBR_DIR.glob("bbr_giacenze_*"), key=lambda p: p.stat().st_mtime)[:-KEEP_BBR]:
        old.unlink(missing_ok=True)
    return dest


# ─────────────────────────── Stato della pipeline (dal log) ────────────────────
PIPELINE_STEPS = {
    1: "Scarico i prodotti da carmodel.com",
    2: "Scarico il listino MCWS",
    3: "Unisco i due elenchi",
    4: "Scrivo le note su Shopify",
}


def pipeline_summary(path: Path | None) -> dict | None:
    """Stato leggibile di una run della pipeline, ricavato dal suo log."""
    if not path or not Path(path).exists():
        return None
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    steps = re.findall(r"[▶▷] \[(\d)/4\]", text)
    merged = re.search(r"RIEPILOGO.*merged: (\d+)", text)
    m = re.search(r"run_(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})", Path(path).name)
    started = datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M") if m else None
    return {
        "step": int(steps[-1]) if steps else 0,
        "finished": "RIEPILOGO" in text,
        "merged": int(merged.group(1)) if merged else 0,
        "problems": [l.strip().lstrip("✗").strip() for l in text.splitlines()
                     if l.strip().startswith("✗") or l.strip().startswith("ERRORE")],
        "started": started,
    }


# ─────────────────────────── File e cartelle ─────────────────────────────────
def latest_mcws_stocklist() -> dict | None:
    """L'ultimo listino MCWS scaricato dalla pipeline (stesso formato di MCWS_stocklist.csv)."""
    files = sorted(MCWS_DIR.glob("mcws_inventory_*.csv"),
                   key=lambda p: p.stat().st_mtime) if MCWS_DIR.exists() else []
    if not files:
        return None
    f = files[-1]
    return {"path": f, "mtime": datetime.fromtimestamp(f.stat().st_mtime)}


def open_in_mac(path: Path, textedit: bool = False) -> bool:
    """Apre un file/cartella sul Mac (TextEdit per i file di testo)."""
    try:
        args = ["open", "-e", str(path)] if textedit else ["open", str(path)]
        return subprocess.run(args, capture_output=True).returncode == 0
    except OSError:
        return False


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
    mtime = datetime.fromtimestamp(f.stat().st_mtime)
    return {"path": f, "name": f.name, "rows": rows,
            "mtime": mtime.strftime("%Y-%m-%d %H:%M"), "when": mtime}


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


def schedule_other_folder() -> str | None:
    """Se la pianificazione esiste ma lancia una ALTRA cartella Vroomi (es. una
    copia vecchia), ritorna quel percorso; altrimenti None."""
    try:
        txt = PLIST_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    if str(RUN_SCRIPT) in txt:
        return None
    m = re.search(r"<string>([^<]*?)/pipeline/run\.sh</string>", txt)
    return m.group(1) if m else "un'altra cartella"


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
