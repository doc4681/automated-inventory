"""
chrome.py — avvio di Chrome "undetected" (per superare Cloudflare).
Funziona sia su Mac Apple Silicon (M1-M4) sia su Mac Intel.

NB: è una COPIA identica di automated-inventory/pipeline/chrome.py, perché questa
cartella deve funzionare anche da sola (zip per Giuliano). Se ne cambi una,
copia la modifica anche nell'altra.

Perché esiste: undetected-chromedriver 3.5.5 scarica SEMPRE il chromedriver per
Mac Intel (mac-x64), anche sui Mac Apple Silicon (M1/M2/M3/M4). Senza Rosetta
quel driver non parte ("Bad CPU type in executable") e tutta la pipeline fallisce.

Qui invece:
  1. Selenium Manager (incluso in selenium) scarica il chromedriver GIUSTO per
     questo Mac (arm64 o x64) e per la versione di Chrome installata;
  2. ne facciamo una copia nostra e applichiamo il patch anti-rilevamento di uc;
  3. la ri-firmiamo (codesign ad-hoc): su Apple Silicon un binario modificato
     senza firma valida viene ucciso da macOS all'avvio;
  4. la passiamo a uc.Chrome, che la usa così com'è (nessun download).
Il driver pronto resta in cache: si rifà da solo solo quando Chrome si aggiorna.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

import undetected_chromedriver as uc
from undetected_chromedriver.patcher import Patcher

CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
)
DRIVER_CACHE = Path.home() / "Library" / "Application Support" / "vroomi" / "chromedriver"


def chrome_major_version() -> int | None:
    """Versione major di Chrome installato (es. 153). Override via env CHROME_MAJOR."""
    env = os.environ.get("CHROME_MAJOR")
    if env and env.isdigit():
        return int(env)
    for path in CHROME_PATHS:
        try:
            out = subprocess.check_output([path, "--version"], text=True, timeout=15)
            m = re.search(r"\b(\d+)\.", out)
            if m:
                return int(m.group(1))
        except Exception:
            continue
    return None


def _driver_runs(path: Path) -> bool:
    try:
        r = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=15)
        return r.returncode == 0 and "ChromeDriver" in r.stdout
    except Exception:
        return False


def _selenium_manager_driver(vmain: int | None) -> Path:
    """Chiede a Selenium Manager il chromedriver per questa architettura/versione."""
    from selenium.webdriver.common.selenium_manager import SeleniumManager
    args = ["--browser", "chrome"]
    if vmain:
        args += ["--browser-version", str(vmain)]
    result = SeleniumManager().binary_paths(args)
    return Path(result["driver_path"])


def ensure_driver(vmain: int | None) -> Path:
    """Ritorna il percorso di un chromedriver patchato, firmato e funzionante."""
    arch = platform.machine()  # arm64 / x86_64
    DRIVER_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        src = _selenium_manager_driver(vmain)
        version = src.parent.name  # .../chromedriver/mac-arm64/<versione>/chromedriver
        dest = DRIVER_CACHE / f"chromedriver_{version}_{arch}"
    except Exception as e:
        # Senza rete Selenium Manager può fallire: riusa un driver già pronto
        # per la stessa versione major di Chrome, se c'è.
        ready = sorted(DRIVER_CACHE.glob(f"chromedriver_{vmain}.*_{arch}"))
        ready = [p for p in ready if _driver_runs(p)]
        if ready:
            print(f"  [Chrome] Selenium Manager non disponibile ({type(e).__name__}) — uso {ready[-1].name}")
            return ready[-1]
        raise RuntimeError(f"Impossibile ottenere il chromedriver: {e}") from e

    if dest.exists() and Patcher(executable_path=str(dest)).is_binary_patched() and _driver_runs(dest):
        return dest

    print(f"  [Chrome] preparo chromedriver {version} ({arch})...")
    tmp = dest.with_suffix(".tmp")
    shutil.copy2(src, tmp)
    tmp.chmod(0o755)
    Patcher(executable_path=str(tmp)).auto()          # patch anti-rilevamento di uc
    subprocess.run(["codesign", "--force", "--sign", "-", str(tmp)],
                   capture_output=True, text=True, check=True)
    if not _driver_runs(tmp):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"chromedriver {version} preparato ma non si avvia")
    tmp.replace(dest)
    for old in DRIVER_CACHE.glob("chromedriver_*"):   # tiene solo quello corrente
        if old != dest:
            old.unlink(missing_ok=True)
    return dest


def new_chrome(headless: bool = False,
               make_options: Callable[[], uc.ChromeOptions] | None = None,
               retries: int = 3) -> uc.Chrome:
    """Avvia una sessione Chrome undetected, con qualche ritentativo.
    make_options: funzione che crea le ChromeOptions — uc non permette di riusare
    lo stesso oggetto dopo un tentativo fallito, quindi ne serve uno nuovo ogni volta."""
    vmain = chrome_major_version()
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            driver_path = ensure_driver(vmain)
            print(f"  [Chrome] avvio (Chrome {vmain}, headless={headless}, driver {driver_path.name})...")
            return uc.Chrome(
                headless=headless,
                use_subprocess=True,
                version_main=vmain,
                options=make_options() if make_options else None,
                driver_executable_path=str(driver_path),
            )
        except Exception as e:
            last_err = e
            print(f"  [Chrome] avvio fallito ({type(e).__name__}: {str(e)[:200]}) — tentativo {attempt}/{retries}")
            time.sleep(5 * attempt)
    raise RuntimeError(f"Impossibile avviare Chrome: {last_err}")
