"""
carmodel_scraper.py
Scrapes product data from https://www.carmodel.com (EN, no /it/).
Credentials ONLY from environment variables:
  os.environ['MCWS_USERNAME']
  os.environ['MCWS_PASSWORD']

Usage:
  python scraper/carmodel_scraper.py --test   # BURAGO only, prints first 3 rows
  python scraper/carmodel_scraper.py          # all brands in Valid_Trademarks.txt
"""

import os
import re
import time
import csv
import argparse
from pathlib import Path

import cloudscraper
from bs4 import BeautifulSoup

BASE_URL = "https://www.carmodel.com"
OUTPUT_FILE = Path(__file__).parent / "carmodel_scraped.csv"
SLEEP = 1.5

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


def make_session() -> cloudscraper.CloudScraper:
    """Create a cloudscraper session; optionally log in with env-var credentials."""
    s = cloudscraper.create_scraper()
    username = os.environ.get("MCWS_USERNAME", "")
    password = os.environ.get("MCWS_PASSWORD", "")
    if username and password:
        r = s.post(f"{BASE_URL}/signin",
                   data={"username": username, "password": password},
                   timeout=20)
        if "/signin" in r.url or "/login" in r.url:
            print("WARNING: login failed — check MCWS_USERNAME / MCWS_PASSWORD")
        else:
            print(f"Logged in as {username}")
    else:
        print("No credentials set (MCWS_USERNAME / MCWS_PASSWORD) — proceeding as guest.")
    return s


def _tooltip(card: BeautifulSoup, title: str) -> str:
    """Extract text from an extra-info span identified by its tooltip title."""
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
    # ">>" link points to the last page
    for a in pag.find_all("a", class_="page-link"):
        if ">>" in a.get_text():
            m = re.search(r"page=(\d+)", a.get("href", ""))
            if m:
                return int(m.group(1))
    # fallback: highest page= value in any link
    return max(
        (int(m.group(1))
         for a in pag.find_all("a", href=True)
         if (m := re.search(r"page=(\d+)", a["href"]))),
        default=1,
    )


def scrape_trademark(session: cloudscraper.CloudScraper, trademark: str) -> list[dict]:
    slug = trademark.lower().replace(" ", "-")
    base = f"{BASE_URL}/trademark/{slug}"
    products = []

    r = session.get(base, timeout=20)
    if r.status_code == 404:
        print(f"  {trademark}: not found, skipping.")
        return []
    if r.status_code != 200:
        print(f"  {trademark}: HTTP {r.status_code}, skipping.")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    total_pages = last_page_number(soup)
    print(f"  [{trademark}] {total_pages} page(s)")

    for page in range(1, total_pages + 1):
        if page > 1:
            time.sleep(SLEEP)
            r = session.get(f"{base}?page={page}", timeout=20)
            if r.status_code != 200:
                print(f"    page {page}: HTTP {r.status_code}, stopping.")
                break
            soup = BeautifulSoup(r.text, "html.parser")

        cards = soup.find_all("article", class_="prod-card")
        page_prods = [p for c in cards if (p := parse_card(c, trademark))]
        products.extend(page_prods)
        print(f"    page {page}/{total_pages}: {len(page_prods)} products (cumulative: {len(products)})")

    return products


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="BURAGO only, print first 3 rows")
    args = parser.parse_args()

    trademarks_file = Path(__file__).parent.parent / "Valid_Trademarks.txt"
    trademarks = ["BURAGO"] if args.test else load_trademarks(trademarks_file)

    session = make_session()
    all_products = []

    for tm in trademarks:
        all_products.extend(scrape_trademark(session, tm))
        if not args.test:
            time.sleep(SLEEP)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_products)

    print(f"\nDone. {len(all_products)} products → {OUTPUT_FILE}")

    if args.test and all_products:
        print("\nPrime 3 righe:")
        print(",".join(FIELDNAMES))
        for row in all_products[:3]:
            print(",".join(str(row[k]) for k in FIELDNAMES))


if __name__ == "__main__":
    main()
