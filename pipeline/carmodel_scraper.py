"""
carmodel_scraper.py
Scrapes product data from https://www.carmodel.com (EN, no /it/).
Usa undetected-chromedriver per bypassare Cloudflare.

Usage:
  python pipeline/carmodel_scraper.py --test   # BURAGO only, stampa prime 3 righe
  python pipeline/carmodel_scraper.py          # tutti i brand in config/Valid_Trademarks.txt
"""

from __future__ import annotations  # compatibilità Python 3.9 (sintassi "X | None")

import os
import re
import time
import csv
import argparse
from pathlib import Path

import undetected_chromedriver as uc
from bs4 import BeautifulSoup

from chrome import new_chrome
from paths import CARMODEL_DIR, TRADEMARKS_FILE, output_file

BASE_URL = "https://www.carmodel.com"
SLEEP = 2


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


def make_driver() -> uc.Chrome:
    # Headless opt-in via env CARMODEL_HEADLESS=1.
    # NB: in headless undetected-chromedriver viene piu' spesso bloccato da
    # Cloudflare; default = finestra visibile (piu' affidabile).
    return new_chrome(headless=os.environ.get("CARMODEL_HEADLESS", "0") == "1")


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
    titolo = ""
    if desc:
        # Dal 2026 il sito mette la marca auto in <b> dentro il titolo: la togliamo
        # (è già in brand_auto) per avere il titolo come prima, es. "F40 1987".
        for b in desc.find_all("b"):
            b.decompose()
        titolo = " ".join(desc.get_text(" ").split())

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


# Pagine/brand persi durante il run: riepilogati alla fine (prima passavano in silenzio).
PAGE_FAILURES: list[str] = []
BRAND_FAILURES: list[str] = []


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
                # Ritenta la singola pagina dopo una pausa. Se non va comunque,
                # si PROSEGUE con le pagine successive: il vecchio 'break' faceva
                # perdere in silenzio tutto il resto del brand.
                pausa = int(os.environ.get("CF_COOLDOWN", "30"))
                print(f"    page {page}: non caricata — attendo {pausa}s e riprovo")
                time.sleep(pausa)
                soup = get_page_soup(driver, f"{base}?page={page}")
            if soup is None:
                print(f"    page {page}/{total_pages}: PERSA (continuo con le altre)")
                PAGE_FAILURES.append(f"{trademark} pag.{page}/{total_pages}")
                continue
            cards = soup.find_all("article", class_="prod-card")

        page_prods = [p for c in cards if (p := parse_card(c, trademark))]
        products.extend(page_prods)
        print(f"    page {page}/{total_pages}: {len(page_prods)} products (cumulative: {len(products)})")

    return products


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="BURAGO only, stampa prime 3 righe")
    args = parser.parse_args()

    trademarks = ["BURAGO"] if args.test else load_trademarks(TRADEMARKS_FILE)

    driver = make_driver()
    all_products = []

    try:
        for i, tm in enumerate(trademarks):
            # Restart Chrome ogni RESTART_EVERY brand (non al primo)
            if not args.test and i > 0 and i % RESTART_EVERY == 0:
                print(f"\n  [Chrome] restart preventivo dopo {i} brand...")
                driver = restart_driver(driver)

            # Ritentativi: su CF meglio ASPETTARE che riavviare a raffica
            # (i riavvii insospettiscono Cloudflare e forzano chiamate di rete).
            MAX_TRIES = 2
            for attempt in range(1, MAX_TRIES + 1):
                try:
                    results = scrape_trademark(driver, tm)
                    all_products.extend(results)
                    break
                except PageLoadError:
                    if attempt < MAX_TRIES:
                        pausa = int(os.environ.get("CF_COOLDOWN", "30"))
                        print(f"  [CF] {tm}: non caricata — attendo {pausa}s e riprovo (stessa sessione)")
                        time.sleep(pausa)
                    else:
                        print(f"  {tm}: skip (Cloudflare non superato).")
                        BRAND_FAILURES.append(f"{tm} (Cloudflare)")
                except (InvalidSessionIdException, NoSuchWindowException) as e:
                    print(f"  [Chrome] crash ({type(e).__name__}) su {tm}, tentativo {attempt}/{MAX_TRIES}")
                    driver = restart_driver(driver)
                    if attempt == MAX_TRIES:
                        print(f"  {tm}: skip dopo {MAX_TRIES} crash.")
                        BRAND_FAILURES.append(f"{tm} (crash Chrome)")

            if not args.test:
                time.sleep(SLEEP)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # Il test scrive in una sottocartella: non deve finire tra i dati veri.
    out_file = output_file(CARMODEL_DIR / "test" if args.test else CARMODEL_DIR, "carmodel_scraped")
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_products)

    print(f"\nDone. {len(all_products)} products → {out_file}")

    if BRAND_FAILURES or PAGE_FAILURES:
        print("\n" + "!" * 60)
        print("SCRAPE INCOMPLETO — questi dati mancano dal file:")
        for b in BRAND_FAILURES:
            print(f"  BRAND PERSO : {b}")
        for p in PAGE_FAILURES:
            print(f"  PAGINA PERSA: {p}")
        print("!" * 60)
        # marcatore accanto al CSV: la pipeline (e chi legge i log) sa che il run
        # e' parziale e che le note/prezzi mancanti non vanno interpretati come
        # 'prodotto senza nota'.
        out_file.with_suffix(".INCOMPLETO.txt").write_text(
            "\n".join(["BRAND PERSI:"] + BRAND_FAILURES +
                      ["", "PAGINE PERSE:"] + PAGE_FAILURES) + "\n",
            encoding="utf-8")

    if args.test and all_products:
        print("\nPrime 3 righe:")
        print(",".join(FIELDNAMES))
        for row in all_products[:3]:
            print(",".join(str(row[k]) for k in FIELDNAMES))
        print(f"\nFile: {out_file}")


if __name__ == "__main__":
    main()
