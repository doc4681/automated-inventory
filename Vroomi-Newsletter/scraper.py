"""
scraper.py — parsing della sidebar 'newsletter recenti' e delle pagine newsletter
di www.modelcarswholesale.com.

Funzioni pure su BeautifulSoup (testabili su HTML salvato):
  parse_sidebar(soup)      -> list[Newsletter]
  parse_newsletter(soup)   -> list[Product]  (con l'etichetta di disponibilità)
  parse_detail(soup)       -> dict con campi extra (materiale, note)
  parse_images(soup, id)   -> list[str] TUTTE le foto del prodotto (versione grande)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from bs4 import BeautifulSoup

import etichette

BASE_URL = "https://www.modelcarswholesale.com"
IMG_BASE = "https://bucket.carmodel.com/images/"
IMG_LARGE = IMG_BASE + "ws-lg/{id}.jpg"
IMG_THUMB = IMG_BASE + "214-161/{id}.jpg"


@dataclass
class Newsletter:
    id: str
    brand: str            # brand come appare nella newsletter (es. 'OTTO-MOBILE')
    date: str             # 'gg-mm-aaaa'
    url: str


@dataclass
class Product:
    site_id: str          # 'codice nostro' interno del sito (es. 204683)
    sku: str              # codice produttore (es. 110023900)
    trademark: str        # brand/marca modellino (es. MINICHAMPS)
    brand_auto: str       # marca automobile (es. BMW)
    description: str      # descrizione senza la marca auto iniziale
    scale: str            # '1/18'
    cost: float | None    # prezzo netto wholesale (il nostro costo)
    availability: str     # 'Dal 17 Lug' / ''
    detail_url: str
    image_url: str        # foto principale (la miniatura della newsletter, in grande)
    image_urls: list[str] = field(default_factory=list)  # TUTTE le foto, la principale per prima
    material: str = ""     # da pagina di dettaglio
    note: str = ""         # da pagina di dettaglio (es. 'WITH OPENINGS - APRIBILE')
    is_special: bool = False  # costo preso da 'Special price' (promo, non listino)
    etichetta: str = ""    # testo dell'etichetta sulla card (es. 'Disponibile', 'Dal 17 Lug')
    disponibilita: str = ""  # etichette.DISPONIBILE / NON_DISPONIBILE / '' (non trovata)

    def as_dict(self) -> dict:
        return asdict(self)


# ── sidebar ──────────────────────────────────────────────────────────────────
_SIDEBAR_RE = re.compile(r"(\d{2}-\d{2}-\d{4})\s*-\s*(.+)")


def parse_sidebar(soup: BeautifulSoup) -> list[Newsletter]:
    """Estrae le newsletter dai link /it/newsletter/{id} con testo 'gg-mm-aaaa - BRAND'."""
    out: list[Newsletter] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=re.compile(r"/newsletter/\d+")):
        href = a["href"]
        m_id = re.search(r"/newsletter/(\d+)", href)
        if not m_id:
            continue
        nid = m_id.group(1)
        if nid in seen:
            continue
        txt = a.get_text(strip=True)
        m = _SIDEBAR_RE.match(txt)
        if not m:
            continue
        date, brand = m.group(1), m.group(2).strip()
        seen.add(nid)
        url = href if href.startswith("http") else BASE_URL + href
        out.append(Newsletter(id=nid, brand=brand, date=date, url=url))
    return out


# ── pagina newsletter ────────────────────────────────────────────────────────
def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _pick(card, *selectors):
    """Primo elemento non-vuoto tra i selettori dati (gestisce varianti desktop/mobile)."""
    for sel in selectors:
        el = card.select_one(sel)
        if el and el.get_text(strip=True):
            return el
    return None


def parse_product_card(card) -> Product | None:
    link = card.select_one(".thumb a[href]") or card.select_one("a[href*='/it/']")
    detail_href = link["href"] if link else ""
    detail_url = detail_href if detail_href.startswith("http") else BASE_URL + detail_href

    # site_id = 'codice nostro' interno = ULTIMO segmento numerico dell'url di
    # dettaglio (l'url e' /it/{tm}/{sku}/{scala}/{auto}/{slug}/{site_id}).
    # E' anche l'id usato per le immagini (ws-lg/{site_id}.jpg).
    img = card.select_one(".thumb img[src]")
    img_src = img["src"].strip() if img else ""

    site_id = ""
    digit_segs = [s for s in detail_href.split("?")[0].split("/") if s.isdigit()]
    if digit_segs:
        site_id = digit_segs[-1]
    if not site_id and img_src:
        mm = re.search(r"/(\d+)(?:-\d+)?\.jpg", img_src)
        if mm:
            site_id = mm.group(1)
    if not site_id:
        return None

    # URL immagine grande: si prende il vero nome-file dalla thumb (es.
    # '198141-3.jpg', il suffisso -N varia per prodotto) e si sostituisce solo la
    # cartella dimensione con 'ws-lg'. Ricostruire da site_id NON basta: molti
    # file hanno un suffisso e 'ws-lg/{site_id}.jpg' darebbe 404.
    if img_src and "/images/" in img_src:
        image_url = large_image_url(img_src)
    else:
        image_url = IMG_LARGE.format(id=site_id)
    # altre foto eventualmente presenti sulla card; le altre arrivano dalla
    # pagina di dettaglio (parse_images), aperta da run.py
    image_urls = merge_images([image_url], _bucket_images(str(card)))

    scale = _text(_pick(card, ".row-one .scale", ".scale"))
    scale = re.sub(r"\s+", "", scale)  # '1/ 18' -> '1/18'
    trademark = _text(_pick(card, ".row-one .trademark", ".trademark"))

    row_two = _pick(card, ".row-two", ".row-two-xs")
    brand_auto, description = "", ""
    if row_two:
        b = row_two.find("b")
        brand_auto = b.get_text(strip=True) if b else ""
        full = row_two.get_text(" ", strip=True)
        description = full
        if brand_auto and full.upper().startswith(brand_auto.upper()):
            description = full[len(brand_auto):].lstrip(" -").strip()

    sku_el = _pick(card, ".row-three b", ".row-three")
    sku = sku_el.get_text(strip=True) if sku_el else ""
    sku = re.split(r"\s{2,}|\n", sku)[0].strip()

    # prezzo di listino (.price); se assente/vuoto, prezzo promo (.special-price)
    cost, is_special = None, False
    price_el = card.select_one(".price")
    if price_el:
        pm = re.search(r"([\d]+[.,][\d]+)", price_el.get_text())
        if pm:
            cost = float(pm.group(1).replace(",", "."))
    if cost is None:
        sp_el = card.select_one(".special-price")
        if sp_el:
            pm = re.search(r"([\d]+[.,][\d]+)", sp_el.get_text())
            if pm:
                cost, is_special = float(pm.group(1).replace(",", ".")), True

    availability = _text(card.select_one(".availableOnText"))
    disponibilita, etichetta = etichette.leggi(card)

    return Product(
        site_id=site_id,
        sku=sku,
        trademark=trademark,
        brand_auto=brand_auto,
        description=description,
        scale=scale,
        cost=cost,
        availability=availability,
        detail_url=detail_url,
        image_url=image_url,
        image_urls=image_urls,
        is_special=is_special,
        etichetta=etichetta,
        disponibilita=disponibilita,
    )


def parse_newsletter(soup: BeautifulSoup, scarti: list | None = None) -> list[Product]:
    """Prodotti della pagina, senza doppioni (stesso site_id). Se si passa la lista
    `scarti`, ci finiscono le card lasciate fuori: (motivo, descrizione) — così il log
    può dire quale prodotto della pagina manca e perché."""
    cards = soup.select("div.product, .row.product")
    matched = {id(c) for c in cards}
    products: list[Product] = []
    for card in cards:
        p = parse_product_card(card)
        if p:
            products.append(p)
        elif scarti is not None:
            # contenitori di altre card (o pezzi di una card) non sono prodotti mancanti
            nested = (any(id(a) in matched for a in card.parents)
                      or any(id(d) in matched for d in card.find_all(True)))
            text = " ".join(card.get_text(" ", strip=True).split())
            if not nested and text:
                scarti.append(("card non letta (senza codice/link)", text[:90]))
    # dedup per site_id preservando l'ordine
    uniq: dict[str, Product] = {}
    for p in products:
        if p.site_id in uniq:
            if scarti is not None and p.sku != uniq[p.site_id].sku:
                scarti.append(("stesso ID sito di un altro prodotto",
                               f"sku={p.sku} (ID {p.site_id}, già usato da sku={uniq[p.site_id].sku})"))
            continue
        uniq[p.site_id] = p
    return list(uniq.values())


# ── pagina di dettaglio ──────────────────────────────────────────────────────
_CODE_LABELS_RE = re.compile(r"Codice nostro|Materiale|Codice produttore|\bEAN\b|Our code|Material|Factory code", re.I)


def parse_detail(soup: BeautifulSoup) -> dict:
    """Campi extra dalla pagina prodotto: materiale e nota.

    La nota (es. 'LIMITED EDITION', 'WITH OPENINGS - APRIBILE', 'TV SERIES')
    si estrae dalla STRUTTURA, non da parole chiave: nel blocco <div class="row">
    che contiene 'Codice nostro:' c'e' un <div class="col-sm-12"> con il testo
    della nota, prima dei div con i codici. Se il prodotto non ha note quel div
    non e' presente e il campo resta vuoto.
    """
    text = soup.get_text("\n", strip=True)
    out = {"material": "", "note": ""}

    m = re.search(r"Materiale:\s*\n?\s*([^\n]+)", text, re.I)
    if m:
        out["material"] = m.group(1).strip()

    anchor = soup.find(string=re.compile(r"Codice nostro:", re.I))
    row = anchor.find_parent("div", class_="row") if anchor else None
    if row is not None:
        cols = row.find_all("div", class_="col-sm-12", recursive=False) \
            or row.find_all("div", recursive=False)
        for col in cols:
            t = col.get_text(" ", strip=True)
            if not t or _CODE_LABELS_RE.search(t):
                continue          # e' uno dei div con i codici, non la nota
            out["note"] = re.sub(r"\s{2,}", " ", t).strip()
            break
    return out


# ── foto ─────────────────────────────────────────────────────────────────────
# Le foto stanno su bucket.carmodel.com/images/{cartella}/{file}: la cartella è
# la dimensione (es. '214-161' miniatura, 'ws-lg' grande). Si cercano in tutto
# l'HTML (src, data-src, data-zoom, href dei link alla foto grande, srcset...) per
# non dipendere da come è fatta la galleria del sito.
_BUCKET_IMG_RE = re.compile(
    r"(?:https?:)?//bucket\.carmodel\.com/images/([\w.-]+)/([\w.-]+\.(?:jpe?g|png|webp))", re.I)
_NUM_STEM_RE = re.compile(r"^(\d+)(?:-\d+)?$")   # '198141' / '198141-3' -> 198141
MAX_IMAGES = 30


def large_image_url(src: str) -> str:
    """Versione grande di una foto del bucket: stesso nome-file .jpg, cartella
    'ws-lg' (le cartelle '*-lg' sono già grandi; gli altri formati restano come sono)."""
    m = _BUCKET_IMG_RE.search(src or "")
    if not m:
        return src
    folder, fname = m.group(1), m.group(2)
    if folder.lower().endswith("-lg") or not fname.lower().endswith(".jpg"):
        return f"{IMG_BASE}{folder}/{fname}"
    return f"{IMG_BASE}ws-lg/{fname}"


def _stem(url: str) -> str:
    return url.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()


def _bucket_images(html: str) -> list[str]:
    """URL (grandi) delle foto del bucket trovate nell'HTML, nell'ordine della pagina."""
    return [large_image_url(m.group(0)) for m in _BUCKET_IMG_RE.finditer(html or "")]


def merge_images(*lists: list[str]) -> list[str]:
    """Unisce liste di foto senza doppioni: la stessa foto in due dimensioni
    (miniatura e grande) conta una volta sola. Max MAX_IMAGES."""
    out: list[str] = []
    seen: set[str] = set()
    for lst in lists:
        for u in lst or []:
            k = _stem(u)
            if u and k not in seen:
                seen.add(k)
                out.append(u)
    return out[:MAX_IMAGES]


def _card_site_ids(card) -> set[str]:
    ids = set()
    for a in card.find_all("a", href=True):
        segs = [s for s in a["href"].split("?")[0].split("/") if s.isdigit()]
        if segs:
            ids.add(segs[-1])
    return ids


def parse_images(soup: BeautifulSoup, site_id: str) -> list[str]:
    """TUTTE le foto del prodotto `site_id` dalla sua pagina di dettaglio (versione
    grande, nell'ordine della galleria). Si escludono le foto di ALTRI prodotti
    mostrati nella pagina (correlati, «potrebbe interessarti»...):
      - quelle dentro una card che porta a un altro prodotto;
      - i file con nome numerico di un altro prodotto (le foto MCWS si chiamano
        {site_id}.jpg o {site_id}-N.jpg)."""
    others: set[str] = set()
    for card in soup.select("div.product, .row.product"):
        ids = _card_site_ids(card)
        if ids and site_id not in ids:
            others.update(_stem(u) for u in _bucket_images(str(card)))
    out = []
    for u in _bucket_images(str(soup)):
        stem = _stem(u)
        m = _NUM_STEM_RE.match(stem)
        if stem in others or (m and m.group(1) != site_id):
            continue
        out.append(u)
    return merge_images(out)
