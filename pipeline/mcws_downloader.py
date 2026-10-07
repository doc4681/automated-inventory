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
import time
from pathlib import Path

import undetected_chromedriver as uc

from chrome import new_chrome
from paths import DATA_DIR, MCWS_DIR, output_file
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchWindowException, InvalidSessionIdException, WebDriverException, TimeoutException,
    StaleElementReferenceException,
)


class CFTimeout(Exception):
    """Cloudflare non superato nei tempi: ritentabile con una sessione Chrome nuova."""


class LoginUnclear(CFTimeout):
    """Dopo l'invio il sito e' rimasto sulla pagina di login senza dire perche'
    (pagina lenta, Cloudflare, campi svuotati dal JavaScript...): si riprova con
    una sessione Chrome nuova prima di concludere che la password e' sbagliata."""


LOGIN_URL = "https://www.modelcarswholesale.com/it/login"
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
    """Supera Cloudflare e fa il login su MCWS. Solleva CFTimeout (ritentabile)
    o SystemExit (credenziali sbagliate/vuote)."""
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

    # Attende il form di login. A volte Cloudflare, dopo il challenge, reindirizza
    # a un'altra pagina (es. la home): in quel caso il campo "username" non c'è.
    # Allora ri-navighiamo esplicitamente al login (ora col lasciapassare CF).
    form_wait = int(os.environ.get("MCWS_FORM_WAIT", "30"))

    def _wait_username():
        WebDriverWait(driver, form_wait).until(
            EC.presence_of_element_located((By.ID, "username")))

    try:
        _wait_username()
    except TimeoutException:
        print(f"  Form login non trovato (url={driver.current_url}, titolo={driver.title!r}) — ri-navigo")
        driver.get(LOGIN_URL)
        time.sleep(3)
        try:
            _wait_username()
        except TimeoutException:
            try:
                campi = driver.execute_script(
                    "return Array.from(document.querySelectorAll('input'))"
                    ".map(i=>i.id+'/'+i.name+'/'+i.type)")
            except Exception:
                campi = "?"
            print(f"  Campi input nella pagina: {campi}")
            # Ritentabile: main() riprova con una sessione Chrome nuova
            raise CFTimeout("form di login MCWS non caricato")

    # Diagnostica SICURA (non stampa la password): se il login viene rifiutato
    # serve capire se le credenziali sono arrivate vuote/corrotte dall'ambiente.
    mask = (username[:2] + "…" + username[-2:]) if len(username) > 4 else "(corta)"
    print(f"  Credenziali caricate: utente='{mask}' (len {len(username)}), password len {len(password)}")
    if not username or not password:
        raise SystemExit(
            "ERRORE: MCWS_USERNAME o MCWS_PASSWORD VUOTI — controlla credenziali.env "
            "(campi tra virgolette, senza spazi).")

    u = driver.find_element(By.ID, "username")
    p = driver.find_element(By.ID, "password")
    _fill(driver, u, username, "utente")
    _fill(driver, p, password, "password")
    submit = driver.find_element(By.CSS_SELECTOR, "button[type=submit], input[type=submit]")
    # click via JavaScript: non fallisce se un banner (es. cookie) copre il pulsante
    driver.execute_script("arguments[0].click();", submit)

    # Attende che il sito lasci la pagina di login. Prima si guardava dopo 3
    # secondi fissi: su Mac/connessioni lente la pagina non era ancora cambiata
    # e il login veniva dato per «rifiutato» anche con la password giusta.
    deadline = time.time() + int(os.environ.get("MCWS_LOGIN_WAIT", "40"))
    msg = ""
    while time.time() < deadline:
        time.sleep(2)
        try:
            title = driver.title
        except WebDriverException:
            continue
        if "Just a moment" in title or "Ci siamo quasi" in title:
            continue
        if not _on_login_page(driver):
            break
        if _stale(u):               # pagina ricaricata ma ancora login: c'e' un motivo?
            msg = _site_error(driver)
            if msg:
                break
    print(f"Post-login URL: {driver.current_url}")

    if _on_login_page(driver):
        if msg:
            raise SystemExit(
                "ERRORE: login rifiutato da MCWS (username/password non accettati)."
                f"\n  Messaggio dal sito: {msg!r}"
                "\n  Controlla in credenziali.env: (1) nessuno spazio prima/dopo il valore; "
                "(2) usa le virgolette SINGOLE se la password ha $ ` \\ o \"; "
                "(3) niente virgolette 'intelligenti' da copia-incolla; (4) valori esatti.")
        # Nessun messaggio dal sito: non e' detto che la password sia sbagliata.
        raise LoginUnclear("MCWS e' rimasto sulla pagina di login senza messaggi")


def _on_login_page(driver: uc.Chrome) -> bool:
    try:
        url = driver.current_url
    except WebDriverException:
        return True
    return "/login" in url or "/signin" in url


def _stale(el) -> bool:
    """True se la pagina che conteneva el e' stata ricaricata."""
    try:
        el.is_enabled()
        return False
    except StaleElementReferenceException:
        return True
    except WebDriverException:
        return False


def _site_error(driver: uc.Chrome) -> str:
    """Messaggio d'errore mostrato dal sito sotto il form (se c'e')."""
    try:
        return driver.execute_script(
            "var el=document.querySelector("
            "'.alert-danger,.invalid-feedback,[role=alert],.error,.help-block,.alert');"
            "return el?el.innerText.trim().slice(0,200):''") or ""
    except Exception:
        return ""


def _fill(driver: uc.Chrome, field, value: str, label: str) -> None:
    """Scrive value nel campo e controlla che ci sia rimasto (su Mac lenti la
    pagina a volte non e' pronta o il JavaScript svuota il campo). Se serve
    riscrive, e come ultima risorsa lo imposta via JavaScript."""
    def current() -> str:
        try:
            return driver.execute_script("return arguments[0].value", field) or ""
        except Exception:
            return ""

    for _ in range(2):
        field.clear()
        field.send_keys(value)
        if current() == value:
            return
        print(f"  Campo {label} non riempito bene ({len(current())}/{len(value)}) — riscrivo")
        time.sleep(1)
    driver.execute_script(
        "arguments[0].value=arguments[1];"
        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", field, value)


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
