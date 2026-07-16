"""
carmodel_scraper.py
Scrapes product data from https://www.carmodel.com (EN, no /it/).
Usa undetected-chromedriver per bypassare Cloudflare.

Usage:
  python scraper/carmodel_scraper.py --test   # BURAGO only, stampa prime 3 righe
  python scraper/carmodel_scraper.py          # tutti i brand in Valid_Trademarks.txt
"""

from __future__ import annotations  # compatibilità Python 3.9 (sintassi "X | None")

import os
import re
import time
import csv
import argparse
from datetime import datetime
from pathlib import Path

import undetected_chromedriver as uc
from bs4 import BeautifulSoup

BASE_URL = "https://www.carmodel.com"
SLEEP = 2


def get_output_file() -> Path:
    ts = os.environ.get("RUN_TIMESTAMP", datetime.now().strftime("%Y-%m-%d_%H%M"))
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    return out_dir / f"carmodel_scraped_{ts}.csv"

FIELDNAMES = [
    "codice_produttore",
    "carmodel_id",
    "trademark",
    "brand_auto",
    "scala",
    "titolo",
    "prezzo",
    "colore",
    "materiale",
    "note",
    "url_prodotto",
    "immagini_url",
]


def load_trademarks(path: Path) -> list[str]:
    marks, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            name = re.sub(r"^\d+\s+", "", line.strip())
            if name and name not in seen:
                marks.append(name)
                seen.add(name)
    return marks


from selenium.common.exceptions import (
    InvalidSessionIdException, NoSuchWindowException, WebDriverException
)

RESTART_EVERY = 10   # riavvia Chrome ogni N brand


import subprocess


def chrome_major_version() -> int | None:
    """Versione major di Chrome installato (es. 148), per allineare il chromedriver.
    Evita l'errore 'ChromeDriver only supports Chrome version X' quando uc scarica
    un driver piu' recente del browser. Override manuale via env CHROME_MAJOR."""
    env = os.environ.get("CHROME_MAJOR")
    if env and env.isdigit():
        return int(env)
    paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    ]
    for path in paths:
        try:
            out = subprocess.check_output([path, "--version"], text=True, timeout=10)
            m = re.search(r"\b(\d+)\.", out)
            if m:
                return int(m.group(1))
        except Exception:
            continue
    return None


def make_driver() -> uc.Chrome:
    # Headless opt-in via env CARMODEL_HEADLESS=1.
    # NB: in headless undetected-chromedriver viene piu' spesso bloccato da
    # Cloudflare; default = finestra visibile (piu' affidabile).
    headless = os.environ.get("CARMODEL_HEADLESS", "0") == "1"
    vmain = chrome_major_version()
    print(f"  [Chrome] avvio sessione (headless={headless}, version_main={vmain})...")
    return uc.Chrome(headless=headless, use_subprocess=True, version_main=vmain)


def restart_driver(driver: uc.Chrome) -> uc.Chrome:
    print("  [Chrome] restart sessione...")
    try:
        driver.quit()
    except Exception:
        pass
    time.sleep(2)
    return make_driver()


def get_page_soup(driver: uc.Chrome, url: str) -> BeautifulSoup | None:
    try:
        driver.get(url)
    except (InvalidSessionIdException, NoSuchWindowException) as e:
        # Sessione/finestra morta: NON saltare il brand — propaga così main()
        # riavvia Chrome subito e ritenta (evita di perdere i brand successivi).
        print(f"  [Chrome] sessione persa ({type(e).__name__}) su {url} — riavvio")
        raise
    except WebDriverException as e:
        print(f"  ERRORE navigazione ({type(e).__name__}): {url}")
        return None
    # Attesa Cloudflare challenge (default 60s, override con env CARMODEL_CF_WAIT).
    # Su Mac lenti/Intel il CF ci mette di più: meglio abbondare.
    cf_iters = max(5, int(os.environ.get("CARMODEL_CF_WAIT", "60")) // 2)
    for _ in range(cf_iters):
        time.sleep(2)
        try:
            title = driver.title
        except (InvalidSessionIdException, NoSuchWindowException) as e:
            print(f"  [Chrome] sessione persa ({type(e).__name__}) — riavvio")
            raise
        except WebDriverException:
            return None
        if "Just a moment" not in title and "Ci siamo quasi" not in title:
            break
    else:
        print(f"  WARNING: CF challenge non risolto per {url}")
        return None
    return BeautifulSoup(driver.page_source, "html.parser")


def _tooltip(card: BeautifulSoup, title: str) -> str:
    span = card.find("span", attrs={"data-bs-title": title})
    if not span:
        return ""
    for icon in span.find_all("i"):
        icon.decompose()
    return span.get_text(strip=True)


def parse_card(card: BeautifulSoup, trademark: str) -> dict | None:
    carmodel_id = card.get("id", "")
    if not carmodel_id:
        return None

    link = card.find("a", class_="article-detail-page-link", href=True)
    if not link:
        return None
    href = link["href"]
    if not href.startswith("http"):
        href = BASE_URL + href

    # URL segments: /{trademark}/{codice}/{scala}/{brand_auto}/{slug}/{id}
    segs = [s for s in href.replace(BASE_URL, "").split("/") if s]
    codice_produttore = segs[1] if len(segs) > 1 else ""
    scala = segs[2].replace("-", "/") if len(segs) > 2 else ""
    brand_auto = segs[3].upper() if len(segs) > 3 else ""

    desc = card.find("p", class_="product-description")
    titolo = desc.get_text(strip=True) if desc else ""

    price_span = card.find("span", class_="actual-price")
    prezzo = ""
    if price_span:
        m = re.search(r"[\d]+[.,][\d]+", price_span.get_text())
        if m:
            prezzo = m.group(0).replace(",", ".")

    colore = _tooltip(card, "Colour")
    materiale = _tooltip(card, "Material")
    note = _tooltip(card, "Notes")

    imgs = [img["src"] for img in card.find_all("img", class_="product-img", src=True)]
    immagini_url = "|".join(imgs)

    return {
        "codice_produttore": codice_produttore,
        "carmodel_id": carmodel_id,
        "trademark": trademark,
        "brand_auto": brand_auto,
        "scala": scala,
        "titolo": titolo,
        "prezzo": prezzo,
        "colore": colore,
        "materiale": materiale,
        "note": note,
        "url_prodotto": href,
        "immagini_url": immagini_url,
    }


def last_page_number(soup: BeautifulSoup) -> int:
    pag = soup.find("ul", class_="pagination")
    if not pag:
        return 1
    for a in pag.find_all("a", class_="page-link"):
        if ">>" in a.get_text():
            m = re.search(r"page=(\d+)", a.get("href", ""))
            if m:
                return int(m.group(1))
    return max(
        (int(m.group(1))
         for a in pag.find_all("a", href=True)
         if (m := re.search(r"page=(\d+)", a["href"]))),
        default=1,
    )


class PageLoadError(Exception):
    """Pagina 1 di un brand non caricata (di solito Cloudflare): ritentabile con sessione nuova."""


def scrape_trademark(driver: uc.Chrome, trademark: str) -> list[dict]:
    slug = trademark.lower().replace(" ", "-")
    base = f"{BASE_URL}/trademark/{slug}"
    products = []

    soup = get_page_soup(driver, base)
    if soup is None:
        # CF non superato / pagina non caricata → ritentabile da main() con sessione nuova
        raise PageLoadError(trademark)

    # Controlla 404 (titolo o assenza di articoli)
    cards = soup.find_all("article", class_="prod-card")
    if not cards and soup.find("h1", string=re.compile(r"404|not found", re.I)):
        print(f"  {trademark}: not found, skipping.")
        return []

    total_pages = last_page_number(soup)
    print(f"  [{trademark}] {total_pages} page(s)")

    for page in range(1, total_pages + 1):
        if page > 1:
            time.sleep(SLEEP)
            soup = get_page_soup(driver, f"{base}?page={page}")
            if soup is None:
                print(f"    page {page}: skip.")
                break
            cards = soup.find_all("article", class_="prod-card")

        page_prods = [p for c in cards if (p := parse_card(c, trademark))]
        products.extend(page_prods)
        print(f"    page {page}/{total_pages}: {len(page_prods)} products (cumulative: {len(products)})")

    return products


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="BURAGO only, stampa prime 3 righe")
    args = parser.parse_args()

    trademarks_file = Path(__file__).parent.parent / "Valid_Trademarks.txt"
    trademarks = ["BURAGO"] if args.test else load_trademarks(trademarks_file)

    driver = make_driver()
    all_products = []

    try:
        for i, tm in enumerate(trademarks):
            # Restart Chrome ogni RESTART_EVERY brand (non al primo)
            if not args.test and i > 0 and i % RESTART_EVERY == 0:
                print(f"\n  [Chrome] restart preventivo dopo {i} brand...")
                driver = restart_driver(driver)

            # Tenta lo scraping con max 3 tentativi (crash sessione o CF non superato):
            # ogni volta si riparte con Chrome nuovo, che spesso passa il Cloudflare.
            MAX_TRIES = 3
            for attempt in range(1, MAX_TRIES + 1):
                try:
                    results = scrape_trademark(driver, tm)
                    all_products.extend(results)
                    break
                except PageLoadError:
                    print(f"  [CF] {tm}: pagina non caricata, tentativo {attempt}/{MAX_TRIES} — riavvio sessione")
                    driver = restart_driver(driver)
                    if attempt == MAX_TRIES:
                        print(f"  {tm}: skip dopo {MAX_TRIES} tentativi (Cloudflare).")
                except (InvalidSessionIdException, NoSuchWindowException) as e:
                    print(f"  [Chrome] crash ({type(e).__name__}) su {tm}, tentativo {attempt}/{MAX_TRIES}")
                    driver = restart_driver(driver)
                    if attempt == MAX_TRIES:
                        print(f"  {tm}: skip dopo {MAX_TRIES} crash.")

            if not args.test:
                time.sleep(SLEEP)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    output_file = get_output_file()
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_products)

    print(f"\nDone. {len(all_products)} products → {output_file}")

    if args.test and all_products:
        print("\nPrime 3 righe:")
        print(",".join(FIELDNAMES))
        for row in all_products[:3]:
            print(",".join(str(row[k]) for k in FIELDNAMES))
        print(f"\nFile: {output_file}")


if __name__ == "__main__":
    main()
