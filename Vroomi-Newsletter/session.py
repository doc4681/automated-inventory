"""
session.py — login e sessione browser per www.modelcarswholesale.com

Usa undetected-chromedriver per superare Cloudflare (stesso approccio della
pipeline `automated-inventory`, che si e' rivelato piu' affidabile del Selenium
classico).

Credenziali lette da ~/.env.vroomi (MCWS_USERNAME / MCWS_PASSWORD).

API:
    drv = make_driver(headless=False)
    login(drv)                       # solleva RuntimeError se fallisce
    soup = get_soup(drv, url)        # BeautifulSoup della pagina (attende Cloudflare)
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import undetected_chromedriver as uc
from bs4 import BeautifulSoup

from chrome import new_chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException,
    InvalidSessionIdException, NoSuchWindowException,
)

BASE_URL = "https://www.modelcarswholesale.com"

class CFTimeout(Exception):
    """Cloudflare non superato / form login non caricato: ritentabile con una
    sessione Chrome nuova."""


# ── credenziali ──────────────────────────────────────────────────────────────
def _load_env_file(path: Path) -> None:
    """Carica un file `export KEY="value"` nell'ambiente (se non gia' presente)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        # accetta valori tra virgolette doppie, singole o senza virgolette
        m = re.match(r"""\s*(?:export\s+)?([A-Z_]+)\s*=\s*(["']?)(.*?)\2\s*$""", line)
        if m:
            os.environ.setdefault(m.group(1), m.group(3))


def get_credentials() -> tuple[str, str]:
    here = Path(__file__).parent
    _load_env_file(here / "credenziali.env")          # cartella da sola (zip per Giuliano)
    _load_env_file(here.parent / "credenziali.env")   # dentro automated-inventory
    _load_env_file(Path.home() / ".env.vroomi")
    user = os.environ.get("MCWS_USERNAME", "").strip()
    pwd = os.environ.get("MCWS_PASSWORD", "").strip()
    if not user or not pwd:
        raise RuntimeError(
            "MCWS_USERNAME / MCWS_PASSWORD mancanti. Impostali in ~/.env.vroomi"
        )
    return user, pwd


# ── driver ───────────────────────────────────────────────────────────────────
def make_driver(headless: bool | None = None) -> uc.Chrome:
    """Chrome undetected con il chromedriver giusto per questo Mac (Intel o
    Apple Silicon): vedi chrome.py."""
    if headless is None:
        headless = os.environ.get("MCW_HEADLESS", "0") == "1"
    try:
        return new_chrome(headless=headless)
    except RuntimeError as e:
        raise CFTimeout(str(e)) from e


# ── Cloudflare / navigazione ─────────────────────────────────────────────────
def _wait_cloudflare(driver: uc.Chrome, timeout: int | None = None) -> None:
    """Attende che la challenge Cloudflare ('Just a moment' / 'Ci siamo quasi')
    sparisca. Se scade solleva CFTimeout (ritentabile con sessione nuova) invece
    di proseguire alla cieca su una pagina bloccata."""
    if timeout is None:
        timeout = int(os.environ.get("MCW_CF_TIMEOUT", "120"))
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        try:
            title = driver.title
        except (InvalidSessionIdException, NoSuchWindowException):
            raise
        except WebDriverException:
            continue
        if "Just a moment" not in title and "Ci siamo quasi" not in title:
            return
    raise CFTimeout(f"Cloudflare non risolto entro {timeout}s")


def get_soup(driver: uc.Chrome, url: str) -> BeautifulSoup | None:
    try:
        driver.get(url)
    except (InvalidSessionIdException, NoSuchWindowException):
        raise
    except WebDriverException as e:
        print(f"  ERRORE navigazione ({type(e).__name__}): {url}", flush=True)
        return None
    _wait_cloudflare(driver)
    return BeautifulSoup(driver.page_source, "html.parser")


# ── login ────────────────────────────────────────────────────────────────────
def is_logged_in(driver: uc.Chrome) -> bool:
    """Euristica: da loggati compare un link di logout / area cliente."""
    html = driver.page_source.lower()
    return any(k in html for k in ("logout", "esci", "my account", "il mio account", "mio conto"))


def login(driver: uc.Chrome) -> None:
    user, pwd = get_credentials()
    print("  [login] apertura sito...", flush=True)
    driver.get(f"{BASE_URL}/it")
    _wait_cloudflare(driver)
    time.sleep(2)

    if is_logged_in(driver):
        print("  [login] gia' autenticato.", flush=True)
        return

    # Vai direttamente alla pagina di login (piu' robusto del click sul bottone)
    for login_url in (f"{BASE_URL}/it/login", f"{BASE_URL}/login", f"{BASE_URL}/it/customer/account/login"):
        driver.get(login_url)
        _wait_cloudflare(driver)
        time.sleep(1.5)
        if driver.find_elements(By.CSS_SELECTOR, "input[type='email'], input[name*='mail'], input[name='username']"):
            break

    # Campo email/username
    EMAIL_SELECTORS = [
        "input[type='email']",
        "input[name*='mail']",
        "input[name='username']",
        "input[name='login']",
        "#email",
    ]
    email_field = _first_element(driver, EMAIL_SELECTORS)
    if not email_field:
        # A volte, dopo il challenge, Cloudflare reindirizza alla home (senza form):
        # ri-navigo esplicitamente al login (ora col lasciapassare CF gia' ottenuto).
        print(f"  [login] form non trovato (url={driver.current_url}, "
              f"titolo={driver.title!r}) — ri-navigo", flush=True)
        driver.get(f"{BASE_URL}/it/login")
        _wait_cloudflare(driver)
        time.sleep(2)
        email_field = _first_element(driver, EMAIL_SELECTORS)
    if not email_field:
        try:
            campi = driver.execute_script(
                "return Array.from(document.querySelectorAll('input'))"
                ".map(i=>i.id+'/'+i.name+'/'+i.type)")
        except Exception:
            campi = "?"
        print(f"  [login] campi input nella pagina: {campi}", flush=True)
        # Ritentabile: la sessione verra' riaperta da BrowserSession.
        raise CFTimeout("form di login MCWS non caricato")
    email_field.clear()
    email_field.send_keys(user)

    # Campo password
    pwd_field = _first_element(driver, [
        "input[type='password']",
        "input[name*='pass']",
        "#password",
    ])
    if not pwd_field:
        raise RuntimeError("Campo password non trovato nella pagina di login.")
    pwd_field.clear()
    pwd_field.send_keys(pwd)

    # Submit
    submit = _first_element(driver, [
        "button[type='submit']",
        "input[type='submit']",
        "button.login",
        "button[name='login']",
    ])
    if submit:
        driver.execute_script("arguments[0].click();", submit)
    else:
        pwd_field.submit()

    _wait_cloudflare(driver)
    time.sleep(3)

    if not is_logged_in(driver):
        raise RuntimeError(
            "Login non riuscito: nessun indicatore di sessione trovato dopo il submit. "
            "Verifica credenziali o selettori."
        )
    print("  [login] autenticazione riuscita.", flush=True)


def _first_element(driver: uc.Chrome, selectors: list[str], timeout: int = 8):
    for sel in selectors:
        try:
            return WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel))
            )
        except (TimeoutException, NoSuchElementException):
            continue
    return None


# ── sessione con auto-recupero ───────────────────────────────────────────────
class BrowserSession:
    """Incapsula driver + login e si auto-recupera se Chrome crasha o Cloudflare
    scade: riapre una sessione nuova (rifacendo login) e ritenta la navigazione.
    L'esecuzione e' idempotente lato Shopify (dedup per SKU), quindi ritentare e'
    sempre sicuro."""

    RECOVERABLE = (NoSuchWindowException, InvalidSessionIdException, CFTimeout)

    def __init__(self, headless: bool | None = None):
        self.headless = headless
        self.drv: uc.Chrome | None = None
        self._open()

    def _open(self) -> None:
        self.drv = make_driver(headless=self.headless)
        login(self.drv)

    def _reopen(self) -> None:
        try:
            if self.drv:
                self.drv.quit()
        except Exception:
            pass
        time.sleep(3)
        self._open()

    def get_soup(self, url: str, retries: int = 2) -> BeautifulSoup | None:
        for attempt in range(retries + 1):
            try:
                return get_soup(self.drv, url)
            except self.RECOVERABLE as e:
                if attempt >= retries:
                    print(f"  [recover] rinuncio dopo {retries+1} tentativi su {url}", flush=True)
                    raise
                print(f"  [recover] {type(e).__name__} — riapro la sessione e riprovo "
                      f"({attempt+1}/{retries})", flush=True)
                self._reopen()
        return None

    def quit(self) -> None:
        try:
            if self.drv:
                self.drv.quit()
        except Exception:
            pass
