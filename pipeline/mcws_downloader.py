"""
mcws_downloader.py
Login su modelcarswholesale.com con undetected-chromedriver (bypassa Cloudflare),
poi scarica il CSV inventario riutilizzando i cookies di sessione.
Credenziali SOLO da variabili d'ambiente:
  os.environ['MCWS_USERNAME']
  os.environ['MCWS_PASSWORD']

Uso:
  python pipeline/mcws_downloader.py
"""

from __future__ import annotations  # compatibilità Python 3.9 (sintassi "X | None")

import os
import sys
import time
from pathlib import Path

import undetected_chromedriver as uc

from chrome import new_chrome
from selenium.common.exceptions import NoSuchWindowException, InvalidSessionIdException
from paths import DATA_DIR, MCWS_DIR, output_file

# Login condiviso con la newsletter (in coda al path: chrome.py e paths.py
# restano quelli di pipeline/, chrome.py e' comunque una copia identica).
sys.path.append(str(Path(__file__).resolve().parent.parent / "Vroomi-Newsletter"))
import session as mcws_session  # noqa: E402

mcws_session.DIAG_DIR = Path(__file__).resolve().parent.parent / "logs"


class CFTimeout(Exception):
    """Cloudflare non superato nei tempi: ritentabile con una sessione Chrome nuova."""


class LoginUnclear(CFTimeout):
    """Dopo l'invio il sito e' rimasto sulla pagina di login senza dire perche'
    (pagina lenta, Cloudflare, campi svuotati dal JavaScript...): si riprova con
    una sessione Chrome nuova prima di concludere che la password e' sbagliata."""


DOWNLOAD_URL = "https://www.modelcarswholesale.com/downloadStocklistCsv"
LOGOUT_URL = "https://www.modelcarswholesale.com/logout"


# Chrome scarica qui (cartella temporanea dedicata); poi il file viene
# rinominato e spostato in dati/mcws/.
DOWNLOAD_DIR = DATA_DIR / ".download_tmp"


def wait_for_download(directory: Path, timeout: int = 60) -> Path | None:
    """Attende che compaia un file .csv scaricato nella directory (prima dello spostamento in dati/mcws/)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Solo file nella directory root, non nelle sottocartelle
        files = [f for f in directory.glob("*.csv")
                 if not f.name.endswith(".crdownload")]
        if files:
            return max(files, key=lambda f: f.stat().st_mtime)
        time.sleep(1)
    return None


def make_options() -> uc.ChromeOptions:
    """Opzioni Chrome per il download automatico (nuove a ogni tentativo)."""
    options = uc.ChromeOptions()
    options.add_experimental_option("prefs", {
        "download.default_directory": str(DOWNLOAD_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    })
    return options


def make_driver() -> uc.Chrome:
    # Headless opt-in via env MCWS_HEADLESS=1.
    # NB: in headless Chrome puo' bloccare i download verso default_directory;
    # default = finestra visibile (download affidabile).
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return new_chrome(headless=os.environ.get("MCWS_HEADLESS", "0") == "1",
                          make_options=make_options)
    except RuntimeError as e:
        raise CFTimeout(str(e)) from e


def login(driver: uc.Chrome, username: str, password: str) -> None:
    """Login su MCWS con la STESSA procedura della newsletter
    (Vroomi-Newsletter/session.py): prima l'inventario ne aveva una copia sua,
    leggermente diversa, che sul Mac del collaboratore falliva mentre la
    newsletter entrava. Solleva CFTimeout/LoginUnclear (ritentabili) o
    SystemExit (credenziali vuote o rifiutate dal sito)."""
    # Diagnostica SICURA (non stampa la password): se il login viene rifiutato
    # serve capire se le credenziali sono arrivate vuote/corrotte dall'ambiente.
    if not username or not password:
        raise SystemExit(
            "ERRORE: MCWS_USERNAME o MCWS_PASSWORD VUOTI — controlla credenziali.env "
            "(campi tra virgolette, senza spazi).")
    try:
        mcws_session.login(driver, username, password)
    except mcws_session.LoginUnclear as e:
        raise LoginUnclear(str(e)) from e
    except mcws_session.CFTimeout as e:
        raise CFTimeout(str(e)) from e
    except RuntimeError as e:
        raise SystemExit(
            f"ERRORE: {e}"
            "\n  Controlla in Impostazioni nome utente e password di MCWS (gli stessi "
            "con cui entri a mano su modelcarswholesale.com).") from e


def download_once(username: str, password: str, out_file: Path) -> None:
    """Un tentativo completo: login → download → logout. Solleva le eccezioni
    di sessione/finestra (NoSuchWindowException/InvalidSessionIdException) così
    main() può ritentare con una sessione Chrome nuova."""
    driver = make_driver()
    try:
        login(driver, username, password)

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
            downloaded.rename(out_file)
            print(f"Salvato: {out_file} ({out_file.stat().st_size} bytes)")
        else:
            # Fallback: il contenuto potrebbe essere inline (non file)
            page_src = driver.page_source
            if "<!DOCTYPE" not in page_src[:100]:
                out_file.write_text(page_src, encoding="utf-8")
                print(f"Salvato (inline): {out_file}")
            else:
                mcws_session.diagnose(driver, "download")
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
    # .strip(): toglie spazi/newline accidentali (copia-incolla) che farebbero
    # fallire il login pur avendo "la password giusta".
    username = os.environ.get("MCWS_USERNAME", "").strip()
    password = os.environ.get("MCWS_PASSWORD", "").strip()
    out_file = output_file(MCWS_DIR, "mcws_inventory")

    MAX_ATTEMPTS = 3
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            download_once(username, password, out_file)
            break
        except (NoSuchWindowException, InvalidSessionIdException, CFTimeout) as e:
            if isinstance(e, LoginUnclear):
                motivo = ("accesso a MCWS non completato: dopo l'invio il sito resta "
                          "sulla pagina di login senza spiegare perche'")
            elif isinstance(e, CFTimeout):
                motivo = "Cloudflare non superato"
            else:
                motivo = "finestra Chrome instabile"
            print(f"  [retry] {motivo} — tentativo {attempt}/{MAX_ATTEMPTS}, riprovo con sessione nuova")
            time.sleep(3)
            if attempt == MAX_ATTEMPTS:
                raise SystemExit(
                    f"ERRORE: download MCWS fallito dopo {MAX_ATTEMPTS} tentativi ({motivo})")

    # Statistiche CSV
    lines = out_file.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"\nRighe nel CSV: {len(lines) - 1}")
    print(f"File: {out_file}")


if __name__ == "__main__":
    main()
