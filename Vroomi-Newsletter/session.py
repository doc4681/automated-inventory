"""
session.py — login e sessione browser per www.modelcarswholesale.com

Usa undetected-chromedriver per superare Cloudflare (stesso approccio della
pipeline `automated-inventory`, che si e' rivelato piu' affidabile del Selenium
classico).

Credenziali MCWS_USERNAME / MCWS_PASSWORD: dall'ambiente (il pannello le passa),
altrimenti da credenziali.env o ~/.env.vroomi; se il sito non fa entrare,
login_any() prova anche le altre salvate sul Mac (vedi credential_candidates).

API:
    drv = make_driver(headless=False)
    login_any(drv)                   # come login(), provando tutte le credenziali salvate
    soup = get_soup(drv, url)        # BeautifulSoup della pagina (attende Cloudflare,
                                     # card annotate con l'etichetta: etichette.py)
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

import undetected_chromedriver as uc
from bs4 import BeautifulSoup

import etichette
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


def _read_env_values(path: Path) -> dict:
    """Valori di un file credenziali, senza toccare l'ambiente."""
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"""\s*(?:export\s+)?([A-Z_]+)\s*=\s*(["']?)(.*?)\2\s*$""", line)
        if m and m.group(3).strip() and m.group(3).strip() not in PLACEHOLDERS:
            out.setdefault(m.group(1), m.group(3).strip())
    return out


def credential_candidates() -> list[tuple[str, str, str]]:
    """Tutte le coppie utente/password MCWS DIVERSE salvate su questo Mac, in
    ordine: quelle passate dal pannello (Impostazioni), poi i file credenziali.env.
    Tra questi c'e' anche ~/Vroomi-Newsletter/credenziali.env, la newsletter
    installata dal Terminale: sul Mac del collaboratore la newsletter entrava con
    quelle, mentre l'inventario usava quelle del pannello, che erano diverse."""
    here = Path(__file__).resolve().parent
    found = [(os.environ.get("MCWS_USERNAME", "").strip(),
              os.environ.get("MCWS_PASSWORD", "").strip(), "Impostazioni del pannello")]
    seen_files = set()
    for f in (here / "credenziali.env",
              here.parent / "credenziali.env",
              Path.home() / "Vroomi-Newsletter" / "credenziali.env",
              Path.home() / ".env.vroomi"):
        try:
            key = f.resolve()
        except OSError:
            continue
        if key in seen_files:
            continue
        seen_files.add(key)
        vals = _read_env_values(f)
        found.append((vals.get("MCWS_USERNAME", ""), vals.get("MCWS_PASSWORD", ""), str(f)))
    out, seen = [], set()
    for user, pwd, src in found:
        if user and pwd and (user, pwd) not in seen:
            seen.add((user, pwd))
            out.append((user, pwd, src))
    return out


def _remember(user: str, pwd: str) -> None:
    """Salva nel pannello (Impostazioni) le credenziali che hanno funzionato, cosi'
    dalla prossima volta si parte da quelle. Solo dentro automated-inventory."""
    root = Path(__file__).resolve().parent.parent
    if not (root / "pannello" / "controller.py").is_file():
        return
    try:
        import sys
        if str(root) not in sys.path:
            sys.path.append(str(root))
        from pannello.controller import save_credentials
        save_credentials({"MCWS_USERNAME": user, "MCWS_PASSWORD": pwd})
        print("  [login] le ho salvate nelle Impostazioni del pannello.", flush=True)
    except Exception as e:
        print(f"  [login] non sono riuscito a salvarle nelle Impostazioni: {e}", flush=True)


def login_any(driver: uc.Chrome) -> None:
    """Login provando, se il sito non fa entrare, anche le ALTRE credenziali
    salvate su questo Mac (vedi credential_candidates). Se entra con credenziali
    diverse da quelle del pannello, le salva nel pannello."""
    cands = credential_candidates()
    if not cands:
        raise RuntimeError(
            "MCWS_USERNAME / MCWS_PASSWORD vuoti o mancanti. Inseriscili nelle "
            "Impostazioni del pannello (o in credenziali.env).")
    errors = []
    for i, (user, pwd, src) in enumerate(cands):
        print(f"  [login] credenziali MCWS da: {src}", flush=True)
        try:
            login(driver, user, pwd)
        except (RuntimeError, LoginUnclear) as e:
            errors.append(e)
            if i + 1 < len(cands):
                print(f"  [login] non entra con queste: provo quelle di {cands[i + 1][2]}",
                      flush=True)
                continue
            # Tutte respinte: se il sito ha detto esplicitamente «no» almeno una
            # volta e' un rifiuto, altrimenti si riprova con una sessione nuova.
            tried = ", ".join(c[2] for c in cands)
            final = next((x for x in errors if not isinstance(x, LoginUnclear)), e)
            if len(cands) > 1:
                raise type(final)(f"{final} (provate le credenziali di: {tried})") from e
            raise
        if i > 0:
            _remember(user, pwd)
        return


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
    # Colori delle etichette di disponibilità (verde = disponibile, azzurra = no):
    # li calcola Chrome e restano sulle card come attributi (vedi etichette.py).
    etichette.annota(driver)
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


def login(driver: uc.Chrome, user: str | None = None, pwd: str | None = None) -> None:
    """Login su MCWS. Usata anche dall'inventario (pipeline/mcws_downloader.py),
    cosi' newsletter e inventario entrano nel sito esattamente allo stesso modo.
    RuntimeError se il sito rifiuta le credenziali, CFTimeout se ritentabile."""
    if user is None or pwd is None:
        user, pwd = get_credentials()
    # Diagnostica SICURA (mai la password): serve a capire se le credenziali
    # arrivano giuste, vuote o con caratteri in piu'.
    mask = (user[:2] + "…" + user[-2:]) if len(user) > 4 else "(corta)"
    # «impronta»: 4 caratteri ricavati dalla password, che non la rivelano ma
    # permettono di vedere se newsletter e inventario usano la STESSA password.
    impronta = hashlib.sha256(pwd.encode()).hexdigest()[:4]
    print(f"  [login] credenziali: utente='{mask}' (len {len(user)}), "
          f"password len {len(pwd)}, impronta {impronta}", flush=True)

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
    _wait_page_ready(driver)   # su Mac lenti il JavaScript puo' rifare il form dopo
    user_field = _first_element(driver, USER_SELECTORS, timeout=5) or user_field

    pwd_field = _first_element(driver, PASS_SELECTORS, timeout=5)
    if not pwd_field:
        raise CFTimeout("campo password non trovato nella pagina di login")
    _fill(driver, user_field, user)
    _fill(driver, pwd_field, pwd)

    # Il pulsante «Accedi» dello STESSO form della password (non quello, per esempio,
    # della ricerca o dell'iscrizione alla newsletter, che puo' venire prima nella pagina).
    submit = driver.execute_script(
        "var f=arguments[0].form; return f ? f.querySelector("
        "'button[type=submit],input[type=submit],button:not([type])') : null;", pwd_field)
    if submit is None:
        submit = _first_element(driver, ["button[type='submit']", "input[type='submit']",
                                         "button.login", "button[name='login']"], timeout=3)
    if submit is not None:
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
        diagnose(driver, "login")
        if msg:
            raise RuntimeError(
                f"login rifiutato da MCWS (username/password non accettati). "
                f"Messaggio dal sito: {msg!r}")
        raise LoginUnclear("MCWS e' rimasto sulla pagina di login senza messaggi")
    print("  [login] autenticazione riuscita.", flush=True)


def _wait_page_ready(driver: uc.Chrome, timeout: int = 15) -> None:
    """Aspetta che la pagina abbia finito di caricarsi (piu' un secondo per il
    JavaScript), prima di scrivere nei campi."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if driver.execute_script("return document.readyState") == "complete":
                break
        except WebDriverException:
            pass
        time.sleep(0.5)
    time.sleep(1)


# Dove salvare la foto della pagina quando il login non va (l'inventario la
# cambia in logs/ del progetto).
DIAG_DIR = Path(__file__).parent / "output"


def diagnose(driver: uc.Chrome, what: str) -> None:
    """Scrive nel log cosa c'e' sulla pagina (mai la password) e ne salva una
    foto: serve a capire, a distanza, perche' il login non e' andato."""
    try:
        info = driver.execute_script("""
            var t = function(e){return (e.innerText||e.value||'').trim().slice(0,40)};
            return {
              url: location.href, title: document.title,
              forms: Array.from(document.forms).map(function(f){
                return (f.getAttribute('action')||'?') + ' [' +
                  Array.from(f.elements).map(function(e){
                    return (e.name||e.id||e.type) + (e.type==='password' ? '' :
                      (e.tagName==='BUTTON'||e.type==='submit' ? '=' + t(e) : ''))
                  }).join(', ') + ']'}),
              messaggi: Array.from(document.querySelectorAll(
                '.alert,.error,.invalid-feedback,.help-block,[role=alert]'))
                .map(t).filter(Boolean).slice(0,5)
            };""")
        print(f"  [diagnosi {what}] pagina: {info.get('url')} — {info.get('title')!r}", flush=True)
        for f in info.get("forms") or []:
            print(f"  [diagnosi {what}] form: {f}", flush=True)
        if info.get("messaggi"):
            print(f"  [diagnosi {what}] messaggi: {info['messaggi']}", flush=True)
    except Exception as e:
        print(f"  [diagnosi {what}] non riesco a leggere la pagina ({type(e).__name__})", flush=True)
    try:
        DIAG_DIR.mkdir(parents=True, exist_ok=True)
        shot = DIAG_DIR / f"mcws_{what}_{time.strftime('%Y-%m-%d_%H%M%S')}.png"
        driver.save_screenshot(str(shot))
        print(f"  [diagnosi {what}] foto della pagina: {shot}", flush=True)
    except Exception:
        pass


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
                login_any(self.drv)
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
