"""
session.py — login e sessione browser per www.modelcarswholesale.com

Usa undetected-chromedriver per superare Cloudflare (stesso approccio della
pipeline `automated-inventory`, che si e' rivelato piu' affidabile del Selenium
classico).

Credenziali MCWS_USERNAME / MCWS_PASSWORD: dall'ambiente (il pannello le passa),
altrimenti da credenziali.env o ~/.env.vroomi.

API:
    drv = make_driver(headless=False)
    login(drv)                       # RuntimeError se rifiutato, CFTimeout se ritentabile
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
from selenium.common.exceptions import (
    WebDriverException, InvalidSessionIdException, NoSuchWindowException,
    StaleElementReferenceException,
)

BASE_URL = "https://www.modelcarswholesale.com"

class CFTimeout(Exception):
    """Cloudflare non superato / form login non caricato: ritentabile con una
    sessione Chrome nuova."""


# ── credenziali ──────────────────────────────────────────────────────────────
PLACEHOLDERS = {"tua-email@esempio.com"}   # valori finti dei file di esempio


def _load_env_file(path: Path) -> list[str]:
    """Carica un file `export KEY="value"` nell'ambiente (se non gia' impostato).
    Ritorna le chiavi impostate davvero da questo file."""
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8").splitlines():
        # accetta valori tra virgolette doppie, singole o senza virgolette
        m = re.match(r"""\s*(?:export\s+)?([A-Z_]+)\s*=\s*(["']?)(.*?)\2\s*$""", line)
        # valori vuoti o di esempio non contano: non devono coprire quelli veri
        # di un file successivo
        if (m and m.group(3).strip() and m.group(3).strip() not in PLACEHOLDERS
                and not os.environ.get(m.group(1), "").strip()):
            os.environ[m.group(1)] = m.group(3)
            loaded.append(m.group(1))
    return loaded


def get_credentials() -> tuple[str, str]:
    here = Path(__file__).parent
    # Dal pannello arrivano gia' nell'ambiente (quelle salvate in Impostazioni):
    # hanno la precedenza sui file qui sotto.
    source = "pannello / ambiente" if os.environ.get("MCWS_PASSWORD") else ""
    for f in (here / "credenziali.env",               # cartella da sola (zip per Giuliano)
              here.parent / "credenziali.env",        # dentro automated-inventory
              Path.home() / ".env.vroomi"):
        if "MCWS_PASSWORD" in _load_env_file(f):
            source = str(f)
    user = os.environ.get("MCWS_USERNAME", "").strip()
    pwd = os.environ.get("MCWS_PASSWORD", "").strip()
    if not user or not pwd:
        raise RuntimeError(
            "MCWS_USERNAME / MCWS_PASSWORD vuoti o mancanti. Inseriscili nelle "
            "Impostazioni del pannello (o in credenziali.env)."
        )
    print(f"  [login] credenziali MCWS da: {source or '?'}", flush=True)
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
# Stessa procedura collaudata di pipeline/mcws_downloader.py (che funziona anche
# sul Mac del collaboratore): pagina di login diretta, campi #username/#password,
# controllo che i campi siano stati riempiti davvero, attesa del cambio pagina.
LOGIN_URL = f"{BASE_URL}/it/login"
USER_SELECTORS = ["#username", "input[name='_username']", "input[name='username']",
                  "input[type='email']", "input[name*='mail']", "#email"]
PASS_SELECTORS = ["#password", "input[name='_password']", "input[type='password']",
                  "input[name*='pass']"]


class LoginUnclear(CFTimeout):
    """Dopo l'invio il sito e' rimasto sulla pagina di login senza dire perche'
    (pagina lenta, campi svuotati dal JavaScript...): si riprova con una
    sessione Chrome nuova, prima di concludere che la password e' sbagliata."""


def is_logged_in(driver: uc.Chrome) -> bool:
    """Euristica: da loggati compare un link di logout / area cliente."""
    html = driver.page_source.lower()
    return any(k in html for k in ("/logout", "my account", "il mio account", "mio conto"))


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


def _fill(driver: uc.Chrome, field, value: str) -> None:
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
        time.sleep(1)
    driver.execute_script(
        "arguments[0].value=arguments[1];"
        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", field, value)


def login(driver: uc.Chrome) -> None:
    user, pwd = get_credentials()
    # Diagnostica SICURA (mai la password): serve a capire se le credenziali
    # arrivano giuste, vuote o con caratteri in piu'.
    mask = (user[:2] + "…" + user[-2:]) if len(user) > 4 else "(corta)"
    print(f"  [login] credenziali: utente='{mask}' (len {len(user)}), "
          f"password len {len(pwd)}", flush=True)

    print("  [login] apertura pagina di login...", flush=True)
    driver.get(LOGIN_URL)
    _wait_cloudflare(driver)

    form_wait = int(os.environ.get("MCW_FORM_WAIT", "30"))
    user_field = _first_element(driver, USER_SELECTORS, timeout=form_wait)
    if not user_field:
        # A volte, dopo il challenge, Cloudflare reindirizza alla home (senza form):
        # ri-navigo esplicitamente al login (ora col lasciapassare CF gia' ottenuto).
        print(f"  [login] form non trovato (url={driver.current_url}, "
              f"titolo={driver.title!r}) — ri-navigo", flush=True)
        driver.get(LOGIN_URL)
        _wait_cloudflare(driver)
        user_field = _first_element(driver, USER_SELECTORS, timeout=form_wait)
    if not user_field:
        try:
            campi = driver.execute_script(
                "return Array.from(document.querySelectorAll('input'))"
                ".map(i=>i.id+'/'+i.name+'/'+i.type)")
        except Exception:
            campi = "?"
        print(f"  [login] campi input nella pagina: {campi}", flush=True)
        # Ritentabile: la sessione verra' riaperta da BrowserSession.
        raise CFTimeout("form di login MCWS non caricato")
    time.sleep(1)  # lascia finire il JavaScript della pagina prima di scrivere

    pwd_field = _first_element(driver, PASS_SELECTORS, timeout=5)
    if not pwd_field:
        raise CFTimeout("campo password non trovato nella pagina di login")
    _fill(driver, user_field, user)
    _fill(driver, pwd_field, pwd)

    submit = _first_element(driver, ["button[type='submit']", "input[type='submit']",
                                     "button.login", "button[name='login']"], timeout=3)
    if submit:
        driver.execute_script("arguments[0].click();", submit)
    else:
        pwd_field.submit()

    # Attende che il sito lasci la pagina di login (su Mac/connessioni lente
    # puo' metterci parecchio: prima si controllava dopo 5 secondi fissi).
    deadline = time.time() + int(os.environ.get("MCW_LOGIN_WAIT", "40"))
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
        if _stale(user_field):      # pagina ricaricata ma ancora login: c'e' un motivo?
            msg = _site_error(driver)
            if msg:
                break
    print(f"  [login] dopo l'invio: {driver.current_url}", flush=True)

    if _on_login_page(driver):
        if msg:
            raise RuntimeError(
                f"login rifiutato da MCWS (username/password non accettati). "
                f"Messaggio dal sito: {msg!r}")
        raise LoginUnclear("MCWS e' rimasto sulla pagina di login senza messaggi")
    print("  [login] autenticazione riuscita.", flush=True)


def _first_element(driver: uc.Chrome, selectors: list[str], timeout: int = 8):
    """Primo elemento VISIBILE tra i selettori, aspettando fino a timeout secondi
    in tutto (non per ciascun selettore)."""
    deadline = time.time() + timeout
    while True:
        for sel in selectors:
            try:
                for el in driver.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed():
                        return el
            except WebDriverException:
                pass
        if time.time() >= deadline:
            return None
        time.sleep(0.5)


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

    def _open(self, attempts: int = 3) -> None:
        """Chrome nuovo + login, con fino a `attempts` tentativi (come la pipeline
        inventario): Cloudflare lento o un login rimasto a meta' si risolvono
        quasi sempre con una sessione nuova. Un rifiuto esplicito del sito NO:
        si ferma subito, per non insistere con una password sbagliata."""
        for attempt in range(1, attempts + 1):
            try:
                self.drv = make_driver(headless=self.headless)
                login(self.drv)
                return
            except self.RECOVERABLE as e:
                self.quit()
                if attempt >= attempts:
                    if isinstance(e, LoginUnclear):
                        raise RuntimeError(
                            f"accesso a MCWS non completato dopo {attempts} tentativi: "
                            "dopo l'invio il sito resta sulla pagina di login senza "
                            "spiegare perche'.") from e
                    raise
                print(f"  [login] {e} — riprovo con una sessione nuova "
                      f"({attempt}/{attempts - 1})", flush=True)
                time.sleep(5 * attempt)
            except Exception:
                self.quit()
                raise

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
