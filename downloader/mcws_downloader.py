"""
mcws_downloader.py
Login su modelcarswholesale.com con undetected-chromedriver (bypassa Cloudflare),
poi scarica il CSV inventario riutilizzando i cookies di sessione.
Credenziali SOLO da variabili d'ambiente:
  os.environ['MCWS_USERNAME']
  os.environ['MCWS_PASSWORD']

Uso:
  python downloader/mcws_downloader.py
"""

from __future__ import annotations  # compatibilità Python 3.9 (sintassi "X | None")

import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

import undetected_chromedriver as uc


def chrome_major_version() -> int | None:
    """Versione major di Chrome installato (es. 148), per allineare il chromedriver.
    Override manuale via env CHROME_MAJOR."""
    env = os.environ.get("CHROME_MAJOR")
    if env and env.isdigit():
        return int(env)
    for path in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    ):
        try:
            out = subprocess.check_output([path, "--version"], text=True, timeout=10)
            m = re.search(r"\b(\d+)\.", out)
            if m:
                return int(m.group(1))
        except Exception:
            continue
    return None
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchWindowException, InvalidSessionIdException, WebDriverException,
)


class CFTimeout(Exception):
    """Cloudflare non superato nei tempi: ritentabile con una sessione Chrome nuova."""


# Chromedriver già scaricato e "patchato": riusarlo evita chiamate di rete a ogni avvio.
UC_CACHED_DRIVER = (Path.home() / "Library" / "Application Support"
                    / "undetected_chromedriver" / "undetected_chromedriver")

LOGIN_URL = "https://www.modelcarswholesale.com/it/login"
DOWNLOAD_URL = "https://www.modelcarswholesale.com/downloadStocklistCsv"
LOGOUT_URL = "https://www.modelcarswholesale.com/logout"


def get_output_file() -> Path:
    ts = os.environ.get("RUN_TIMESTAMP", datetime.now().strftime("%Y-%m-%d_%H%M"))
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    return out_dir / f"mcws_inventory_{ts}.csv"


# Chrome scarica nella directory temporanea del downloader (non output/)
# così wait_for_download trova il file prima del rename
DOWNLOAD_DIR = Path(__file__).parent.resolve()


def wait_for_download(directory: Path, timeout: int = 60) -> Path | None:
    """Attende che compaia un file .csv scaricato nella directory (non in output/)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Solo file nella directory root, non nelle sottocartelle
        files = [f for f in directory.glob("*.csv")
                 if not f.name.endswith(".crdownload")]
        if files:
            return max(files, key=lambda f: f.stat().st_mtime)
        time.sleep(1)
    return None


def make_driver() -> uc.Chrome:
    """Crea una sessione Chrome configurata per il download automatico."""
    options = uc.ChromeOptions()
    prefs = {
        "download.default_directory": str(DOWNLOAD_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)
    # Headless opt-in via env MCWS_HEADLESS=1.
    # NB: in headless Chrome puo' bloccare i download verso default_directory;
    # default = finestra visibile (download affidabile).
    headless = os.environ.get("MCWS_HEADLESS", "0") == "1"
    vmain = chrome_major_version()
    last_err = None
    for attempt in range(1, 4):
        # 1° tentativo con il driver in cache: evita che uc contatti internet
        # (su alcune reti la richiesta viene rifiutata e fa fallire la run).
        kwargs = dict(headless=headless, use_subprocess=True, options=options, version_main=vmain)
        if attempt == 1 and UC_CACHED_DRIVER.exists():
            kwargs["driver_executable_path"] = str(UC_CACHED_DRIVER)
        try:
            print(f"Avvio Chrome (undetected, headless={headless}, version_main={vmain})...")
            return uc.Chrome(**kwargs)
        except Exception as e:
            last_err = e
            print(f"  [Chrome] avvio fallito ({type(e).__name__}) — tentativo {attempt}/3")
            time.sleep(5 * attempt)
    raise CFTimeout(f"Impossibile avviare Chrome: {last_err}")


def download_once(username: str, password: str, output_file: Path) -> None:
    """Un tentativo completo: login → download → logout. Solleva le eccezioni
    di sessione/finestra (NoSuchWindowException/InvalidSessionIdException) così
    main() può ritentare con una sessione Chrome nuova."""
    driver = make_driver()
    try:
        # Login
        print(f"Navigazione verso {LOGIN_URL}")
        driver.get(LOGIN_URL)

        # Attesa Cloudflare challenge (default 120s, override con env MCWS_CF_TIMEOUT).
        # Su Mac lenti/Intel il CF ci mette di più: se scade, main() ritenta con sessione nuova.
        cf_secs = int(os.environ.get("MCWS_CF_TIMEOUT", "120"))
        for i in range(cf_secs // 2):
            time.sleep(2)
            title = driver.title
            if "Just a moment" not in title and "Ci siamo quasi" not in title:
                print(f"Challenge superato ({(i+1)*2}s) — titolo: {title}")
                break
            if (i + 1) % 5 == 0:
                print(f"  Attesa CF... {(i+1)*2}s")
        else:
            raise CFTimeout(f"Cloudflare challenge non risolto dopo {cf_secs}s")

        # Compila form di login
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.ID, "username")))
        driver.find_element(By.ID, "username").send_keys(username)
        driver.find_element(By.ID, "password").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, "button[type=submit], input[type=submit]").click()
        time.sleep(3)
        print(f"Post-login URL: {driver.current_url}")

        if "/login" in driver.current_url or "/signin" in driver.current_url:
            raise SystemExit("ERRORE: login fallito — controlla le credenziali")

        # Download CSV direttamente con Chrome (bypassa CF)
        print(f"Download da {DOWNLOAD_URL}...")
        # Rimuovi eventuali CSV vecchi nella dir root per non confonderli
        for old in DOWNLOAD_DIR.glob("*.csv"):
            old.unlink()

        driver.get(DOWNLOAD_URL)
        time.sleep(2)  # breve pausa per avviare il download

        # Attendi completamento download
        downloaded = wait_for_download(DOWNLOAD_DIR, timeout=60)
        if downloaded:
            downloaded.rename(output_file)
            print(f"Salvato: {output_file} ({output_file.stat().st_size} bytes)")
        else:
            # Fallback: il contenuto potrebbe essere inline (non file)
            page_src = driver.page_source
            if "<!DOCTYPE" not in page_src[:100]:
                output_file.write_text(page_src, encoding="utf-8")
                print(f"Salvato (inline): {output_file}")
            else:
                raise SystemExit("ERRORE: download non completato")

        # Logout
        driver.get(LOGOUT_URL)
        print(f"Logout: {driver.current_url}")

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def main():
    username = os.environ["MCWS_USERNAME"]
    password = os.environ["MCWS_PASSWORD"]
    output_file = get_output_file()

    MAX_ATTEMPTS = 3
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            download_once(username, password, output_file)
            break
        except (NoSuchWindowException, InvalidSessionIdException, CFTimeout) as e:
            motivo = "Cloudflare non superato" if isinstance(e, CFTimeout) else "finestra Chrome instabile"
            print(f"  [retry] {motivo} — tentativo {attempt}/{MAX_ATTEMPTS}, riprovo con sessione nuova")
            time.sleep(3)
            if attempt == MAX_ATTEMPTS:
                raise SystemExit(
                    f"ERRORE: download MCWS fallito dopo {MAX_ATTEMPTS} tentativi ({motivo})")

    # Statistiche CSV
    lines = output_file.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"\nRighe nel CSV: {len(lines) - 1}")
    print(f"File: {output_file}")


if __name__ == "__main__":
    main()
