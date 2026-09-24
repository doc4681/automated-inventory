"""
mcws_newsletter.py — prodotti di una newsletter MCWS → nuovi prodotti Shopify (BOZZA).

Su modelcarswholesale.com, dopo il login, la colonna "Recent Newsletters" elenca le
newsletter (es. "24-09-2026 - MR-MODELS"): ognuna è una lista di prodotti nuovi.
Questo script:
  1. entra su MCWS, legge l'elenco newsletter e apre quella scelta (default: la prima);
  2. per ogni prodotto prende codice, ID, marca, descrizione, scala, prezzo netto;
  3. lo arricchisce con i dati carmodel già scaricati (foto, materiale, colore, note):
     l'ID MCWS è lo stesso carmodel_id;
  4. costruisce il prodotto nel formato di quelli già su Shopify (titolo, tag,
     SKU = codice produttore, barcode = ID MCWS, costo, prezzo con le regole di
     ricarico del pannello, metafield custom.*, foto grandi) e — solo con --apply —
     lo crea su Shopify in stato BOZZA.
I prodotti già presenti su Shopify (stesso SKU o barcode) vengono saltati.

Uso:
  python pipeline/mcws_newsletter.py --list            # elenca le newsletter recenti
  python pipeline/mcws_newsletter.py                   # PROVA sulla 1ª newsletter (non scrive nulla)
  python pipeline/mcws_newsletter.py --index 3         # la 3ª della lista
  python pipeline/mcws_newsletter.py --url https://www.modelcarswholesale.com/newsletter/15542
  python pipeline/mcws_newsletter.py --apply           # crea davvero i prodotti (BOZZA)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from paths import CARMODEL_DIR, DATA_DIR, MARKUP_FILE, ROOT, TRADEMARKS_FILE, latest_file, run_timestamp

BASE = "https://www.modelcarswholesale.com"
LOGOUT_URL = f"{BASE}/logout"
IMG_BASE = "https://bucket.carmodel.com/images"
API_VERSION = "2025-07"          # productSet con foto + inventoryItem in un'unica chiamata
REPORT_DIR = DATA_DIR / "newsletter"

sys.path.insert(0, str(ROOT))    # per riusare le regole di prezzo del pannello
from pannello.logic_v03 import (  # noqa: E402
    calculate_target_price_and_markup, load_markup_rules, load_trademarks, normalize_string,
)


def log(msg: str = "") -> None:
    print(msg, flush=True)


# ─────────────────────────── 1-2. Lettura da MCWS ─────────────────────────────
def parse_newsletter_links(html: str) -> list[tuple[str, str]]:
    """[(titolo, url)] della colonna "Recent Newsletters", in ordine, senza doppioni."""
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href, text = a["href"], a.get_text(" ", strip=True)
        m = re.search(r"/newsletter/(\d+)$", href)
        if m and text and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append((text, BASE + f"/newsletter/{m.group(1)}"))
    return out


def _price(text: str) -> float:
    m = re.search(r"([\d.,]+)", text.replace("€", ""))
    if not m:
        return 0.0
    num = m.group(1)
    if "," in num and "." in num:          # 1,234.50
        num = num.replace(",", "")
    elif "," in num:                       # 352,20
        num = num.replace(",", ".")
    return float(num)


def parse_newsletter_products(html: str) -> tuple[str, list[dict]]:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    products = []
    for block in soup.select("div.row.product"):
        def txt(sel):
            el = block.select_one(sel)
            return el.get_text(" ", strip=True) if el else ""
        row_two = block.select_one(".row-two") or block.select_one(".row-two-xs")
        car_brand = row_two.find("b").get_text(strip=True) if row_two and row_two.find("b") else ""
        desc = row_two.get_text(" ", strip=True) if row_two else ""
        desc = re.sub(r"^" + re.escape(car_brand) + r"\s*-?\s*", "", desc).strip()
        code_el = block.select_one(".row-three b")
        link = block.select_one(".thumb a[href]")
        pid = ""
        m = re.search(r"ID:\s*(\d+)", block.get_text(" ", strip=True))
        if m:
            pid = m.group(1)
        products.append({
            "id": pid,
            "code": code_el.get_text(strip=True) if code_el else "",
            "trademark": txt(".row-one .trademark") or txt(".row-one-xs .trademark"),
            "scale": txt(".row-one .scale") or txt(".row-one-xs .scale"),
            "car_brand": car_brand,
            "description": desc,
            "availability": txt(".availableOnText"),
            "new": bool(block.select_one(".newText")),
            "net_price": _price(txt(".price")),
            "url": BASE + link["href"] if link else "",
        })
    return title, [p for p in products if p["id"] and p["code"]]


def read_from_mcws(index: int, url: str | None, list_only: bool):
    """Login su MCWS (Chrome), legge l'elenco newsletter e quella scelta."""
    from mcws_downloader import login, make_driver
    username = os.environ.get("MCWS_USERNAME", "").strip()
    password = os.environ.get("MCWS_PASSWORD", "").strip()
    driver = make_driver()
    try:
        login(driver, username, password)
        links = parse_newsletter_links(driver.page_source)
        if list_only:
            return links, None, None, []
        if not url:
            if not links:
                raise SystemExit("ERRORE: nessuna newsletter trovata nella pagina MCWS.")
            if not 1 <= index <= len(links):
                raise SystemExit(f"ERRORE: --index {index} fuori range (1..{len(links)}).")
            url = links[index - 1][1]
        driver.get(url)
        time.sleep(3)
        title, products = parse_newsletter_products(driver.page_source)
        return links, url, title, products
    finally:
        try:
            driver.get(LOGOUT_URL)
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass


# ─────────────────────────── 3. Dati carmodel ─────────────────────────────────
EXCLUDE_NOTE_PHRASE = "EXCLUSIVE CARMODEL"   # stessa regola del merger


def load_carmodel_index() -> dict[str, dict]:
    f = latest_file(CARMODEL_DIR, "carmodel_scraped")
    if not f:
        log("  (nessuno scrape carmodel in dati/carmodel: foto/materiale presi solo da MCWS)")
        return {}
    with open(f, newline="", encoding="utf-8") as fh:
        return {r["carmodel_id"]: r for r in csv.DictReader(fh)}


def large_images(cm: dict | None, pid: str) -> list[str]:
    """Foto grandi: le miniature carmodel (images/310-228/<nome>.webp) esistono
    anche in images/cm-lg/<nome>.jpg. Fallback: la foto MCWS images/ws-lg/<id>.jpg."""
    names = []
    for u in ((cm or {}).get("immagini_url") or "").split("|"):
        name = Path(u.strip()).stem
        if name and name not in names:
            names.append(name)
    urls = [f"{IMG_BASE}/cm-lg/{n}.jpg" for n in names] or [f"{IMG_BASE}/ws-lg/{pid}.jpg"]
    ok = []
    for u in urls:
        try:
            if requests.head(u, timeout=15).status_code == 200:
                ok.append(u)
        except requests.RequestException:
            pass
    return ok


# ─────────────────────────── 4. Prodotto Shopify ──────────────────────────────
CATEGORY_KEYWORDS = [   # fallback se non c'è un prodotto "fratello" su Shopify
    ("HELMETS", r"\bHELMET\b|\bCASCO\b"),
    ("TRUCKS", r"\bTRUCK\b|\bCAMION\b|\bTRACTOR\b"),
    ("RACING CARS", r"\bF1\b|\bRALLY\b|\bLE MANS\b|\bGP\b|\bRACING\b|\bN \d+\b|\bDTM\b|\bWEC\b|\bINDY"),
]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def split_model_year(description: str) -> tuple[str, str]:
    first = description.split(" - ")[0].strip()
    m = re.search(r"\b(19\d{2}|20\d{2})\b(?!.*\b(19|20)\d{2}\b)", first)
    year = m.group(1) if m else ""
    model = re.sub(r"\s+", " ", first.replace(year, "")).strip() if year else first
    return model, year


class Shopify:
    def __init__(self, domain: str, token: str):
        self.url = f"https://{domain}/admin/api/{API_VERSION}/graphql.json"
        self.headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    def gql(self, query: str, variables: dict | None = None) -> dict:
        for attempt in range(5):
            r = requests.post(self.url, headers=self.headers, timeout=60,
                              json={"query": query, "variables": variables or {}})
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            data = r.json()
            if "errors" in data:
                if any("throttl" in str(e).lower() for e in data["errors"]) and attempt < 4:
                    time.sleep(2 ** attempt + 1)
                    continue
                raise RuntimeError(f"GraphQL errors: {data['errors']}")
            return data["data"]
        raise RuntimeError("GraphQL: troppi retry")

    def variants(self, query: str) -> list[dict]:
        q = """query($q:String){ productVariants(first:20, query:$q){ nodes{
                 sku barcode product{ title status productType } } } }"""
        return self.gql(q, {"q": query})["productVariants"]["nodes"]


def guess_category(shop: Shopify, code: str, vendor: str, text: str) -> tuple[str, str]:
    """Categoria (productType): prima dai prodotti 'fratelli' già su Shopify
    (stesso prefisso codice, es. BUG015*), poi da parole chiave."""
    m = re.match(r"^[A-Za-z]+\d+", code)
    if m:
        types = [v["product"]["productType"] for v in shop.variants(f"sku:{m.group(0)}*")
                 if v["product"]["productType"]]
        if types:
            best = max(set(types), key=types.count)
            return best, f"come i prodotti simili {m.group(0)}* già su Shopify"
    for cat, rx in CATEGORY_KEYWORDS:
        if re.search(rx, text.upper()):
            return cat, "da parole chiave nel titolo"
    return "ROAD CARS", "default (nessun indizio): CONTROLLA"


def build_product(p: dict, cm: dict | None, shop: Shopify, markup_rules, valid_tm) -> dict:
    vendor = p["trademark"].replace("-", " ").upper()
    scale = p["scale"].replace("/", ":")
    title = f"{p['car_brand']} - {p['description']}" if p["car_brand"] else p["description"]
    model, year = split_model_year(p["description"])
    material = ((cm or {}).get("materiale") or "").upper()
    note = ((cm or {}).get("note") or "").strip()
    if EXCLUDE_NOTE_PHRASE in note.upper():
        note = ""
    category, cat_reason = guess_category(shop, p["code"], vendor, title + " " + note)

    cost = p["net_price"]
    price, markup, price_reason = calculate_target_price_and_markup(
        cost, "", p["trademark"], markup_rules, valid_tm)

    nice = " ".join(w.capitalize() for w in f"{p['car_brand']} {model} {year}".split())
    images = large_images(cm, p["id"])
    mf = {
        "scale": ("single_line_text_field", scale),
        "car_brand": ("single_line_text_field", p["car_brand"]),
        "car_model": ("single_line_text_field", model),
        "category": ("single_line_text_field", category),
        "year": ("single_line_text_field", year),
        "model_manufacturer": ("single_line_text_field", vendor),
        "manufacturer": ("single_line_text_field", vendor),
        "distributor": ("single_line_text_field", "MCWS"),
        "highlights": ("list.single_line_text_field", json.dumps([scale])),
        "availability": ("single_line_text_field", "no"),
        "material": ("single_line_text_field", material),
        "notes": ("single_line_text_field", note),
    }
    return {
        "_info": {"markup": markup, "price_reason": price_reason, "category_reason": cat_reason,
                  "carmodel": bool(cm), "availability": p["availability"], "mcws_url": p["url"]},
        "input": {
            "title": title,
            "handle": f"{slug(title)[:40].strip('-')}-{p['code'].lower()}",
            "descriptionHtml": "<p>-</p>",
            "vendor": vendor,
            "productType": category,
            "status": "DRAFT",
            "tags": [t for t in (scale, p["car_brand"], vendor, category) if t],
            "seo": {"title": f"{nice} Scale Model Car",
                    "description": f"{nice} scale model car. Detailed replica for collectors. Available at Vroomi."},
            "metafields": [{"namespace": "custom", "key": k, "type": t, "value": v}
                           for k, (t, v) in mf.items() if v],
            "productOptions": [{"name": "Title", "values": [{"name": "Default Title"}]}],
            "variants": [{
                "optionValues": [{"optionName": "Title", "name": "Default Title"}],
                "price": f"{price:.2f}",
                "barcode": p["id"],
                "inventoryPolicy": "DENY",
                "taxable": True,
                "inventoryItem": {"sku": p["code"].upper(), "cost": f"{cost:.2f}",
                                  "tracked": True, "requiresShipping": True},
            }],
            "files": [{"originalSource": u, "contentType": "IMAGE",
                       "alt": f"{nice} {scale} scale model car by {vendor} — Vroomi"}
                      for u in images],
        },
    }


PRODUCT_SET = """mutation($input: ProductSetInput!) {
  productSet(synchronous: true, input: $input) {
    product { id handle title status }
    userErrors { field message code }
  }
}"""


# ─────────────────────────────────── main ────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="elenca le newsletter recenti ed esce")
    ap.add_argument("--index", type=int, default=1, help="quale newsletter (1 = la più recente)")
    ap.add_argument("--url", help="URL diretto di una newsletter MCWS")
    ap.add_argument("--apply", action="store_true", help="crea DAVVERO i prodotti su Shopify (BOZZA)")
    args = ap.parse_args()

    log("▶ MCWS: login e lettura newsletter...")
    links, url, nl_title, products = read_from_mcws(args.index, args.url, args.list)
    if args.list:
        for i, (t, u) in enumerate(links, 1):
            log(f"  {i:3d}. {t}   {u}")
        return
    log(f"\nNewsletter: {nl_title}\n  {url}\n  prodotti trovati: {len(products)}")
    if not products:
        raise SystemExit("ERRORE: nessun prodotto letto dalla newsletter (pagina cambiata?).")

    from shopify_enricher import get_access_token
    domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "scn8p4-h7.myshopify.com")
    shop = Shopify(domain, get_access_token(domain))
    carmodel = load_carmodel_index()
    with open(MARKUP_FILE, encoding="utf-8") as f:
        markup_rules = load_markup_rules(f)
    with open(TRADEMARKS_FILE, encoding="utf-8") as f:
        valid_tm = load_trademarks(f)

    report = []
    for n, p in enumerate(products, 1):
        log(f"\n── [{n}/{len(products)}] {p['trademark']} {p['code']} (ID {p['id']}) ──")
        existing = shop.variants(f"sku:{p['code']}") + shop.variants(f"barcode:{p['id']}")
        if existing:
            e = existing[0]
            log(f"  ⏭  già su Shopify: {e['product']['title']} ({e['product']['status']}) — salto")
            report.append({**p, "esito": "già presente"})
            continue
        if normalize_string(p["trademark"]) not in valid_tm:
            log(f"  ⚠️  {p['trademark']} non è in config/Valid_Trademarks.txt (lo creo comunque)")
        cm = carmodel.get(p["id"])
        prod = build_product(p, cm, shop, markup_rules, valid_tm)
        inp, info = prod["input"], prod["_info"]
        v = inp["variants"][0]
        log(f"  Titolo     : {inp['title']}")
        log(f"  Marca/Tipo : {inp['vendor']} / {inp['productType']}  ({info['category_reason']})")
        log(f"  Tag        : {', '.join(inp['tags'])}")
        log(f"  SKU/Barcode: {v['inventoryItem']['sku']} / {v['barcode']}")
        log(f"  Costo→Prezzo: €{v['inventoryItem']['cost']} × {info['markup']} → €{v['price']}  ({info['price_reason']})")
        log(f"  Disponibile: {info['availability'] or '-'}   dati carmodel: {'sì' if info['carmodel'] else 'NO'}")
        log(f"  Campi      : " + ", ".join(f"{m['key']}={m['value']}" for m in inp["metafields"]))
        log(f"  Foto       : {len(inp['files'])} " + " ".join(f["originalSource"] for f in inp["files"]))
        log(f"  SEO        : {inp['seo']['title']}")

        if not args.apply:
            report.append({**p, "esito": "prova (non creato)", "prezzo": v["price"]})
            continue
        res = shop.gql(PRODUCT_SET, {"input": inp})["productSet"]
        if res["userErrors"]:
            log(f"  ✗ ERRORE Shopify: {res['userErrors']}")
            report.append({**p, "esito": f"errore: {res['userErrors']}"})
            continue
        pr = res["product"]
        admin = f"https://admin.shopify.com/store/{domain.split('.')[0]}/products/{pr['id'].split('/')[-1]}"
        log(f"  ✓ CREATO in BOZZA: {pr['title']}\n    {admin}")
        report.append({**p, "esito": "creato (bozza)", "prezzo": v["price"], "shopify": admin})

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"newsletter_{url.rsplit('/', 1)[-1]}_{run_timestamp()}.csv"
    keys = sorted({k for r in report for k in r})
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(report)
    count = lambda prefix: sum(r["esito"].startswith(prefix) for r in report)
    log(f"\nRIEPILOGO: {count('creato')} creati, {count('prova')} da creare, "
        f"{count('già')} già presenti, {count('errore')} errori — report: {out}")
    if not args.apply and count("prova"):
        log("Nessuna modifica su Shopify. Per crearli davvero (in BOZZA) aggiungi  --apply")

if __name__ == "__main__":
    main()
