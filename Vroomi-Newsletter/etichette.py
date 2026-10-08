"""
etichette.py — l'etichetta di disponibilità sulle card dei prodotti
(modelcarswholesale.com e carmodel.com, stesso sito sotto).

Ogni prodotto ha un'etichetta colorata:
  • «Disponibile» → scritta bianca su VERDE  → il prodotto si processa normalmente
  • tutte le altre (es. «Dal 17 Lug», «In arrivo», «Preordine») → scritta bianca su
    AZZURRO → il prodotto NON è disponibile e si salta (newsletter e inventario).

Come si legge: il colore lo calcola il browser. Prima di prendere l'HTML della pagina,
annota(driver) esegue ANNOTA_JS in Chrome: per ogni card cerca le scritte bianche su
fondo verde o azzurro (bottoni e prezzi esclusi) e scrive sulla card gli attributi
data-vroomi-etichetta (il testo) e data-vroomi-colore («verde» / «azzurro»). Così non
dipende dai nomi delle classi CSS del sito. leggi(card) li rilegge da BeautifulSoup;
se mancano (pagina presa senza Chrome) prova a riconoscere l'etichetta da testo e classi.

Se l'etichetta non si trova il prodotto si processa come prima (mai saltare alla cieca),
ma va segnalato nel log: vuol dire che il sito è cambiato.

NB: modulo condiviso: lo usano anche pipeline/carmodel_scraper.py (catalogo) e
pannello/inventario_sync.py (inventario). Sta qui perché questa cartella deve
funzionare anche da sola (zip per Giuliano).
"""

from __future__ import annotations

import re

DISPONIBILE = "disponibile"
NON_DISPONIBILE = "non disponibile"
SCONOSCIUTA = ""                 # etichetta non trovata: si processa come prima

# Card prodotto: newsletter / pagine MCWS (div.product) e carmodel.com (article.prod-card)
CARD_SELECTOR = "div.product, .row.product, article.prod-card"

ATTR_TESTO = "data-vroomi-etichetta"
ATTR_COLORE = "data-vroomi-colore"
ATTR_TUTTE = "data-vroomi-etichette"     # tutte le etichette viste (per i controlli)

# Etichette colorate che NON parlano di disponibilità (promo, novità): ignorate.
_NON_DISPONIBILITA_RE = re.compile(
    r"special|offert|promo|scont|sale\b|saldi|new\b|nuov|novit|exclusive|esclusiv|limited|limitat",
    re.I)
_TESTO_DISPONIBILE_RE = re.compile(
    r"^\s*(disponibile|disponibili|available|in stock|pronta consegna)\s*!?\s*$", re.I)

ANNOTA_JS = r"""
var sel = arguments[0];
function rgba(s) {
  var m = /rgba?\(([^)]+)\)/.exec(s || '');
  if (!m) return null;
  var p = m[1].split(',').map(function (x) { return parseFloat(x); });
  if (p.length > 3 && p[3] < 0.5) return null;          // trasparente
  return p;
}
function colore(c) {
  var r = c[0] / 255, g = c[1] / 255, b = c[2] / 255;
  var max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (max === 0 || d / max < 0.25 || d < 0.12) return '';  // grigio / bianco / nero
  var h;
  if (max === r) h = 60 * (((g - b) / d) % 6);
  else if (max === g) h = 60 * ((b - r) / d + 2);
  else h = 60 * ((r - g) / d + 4);
  if (h < 0) h += 360;
  if (h >= 70 && h < 170) return 'verde';
  if (h >= 170 && h < 265) return 'azzurro';
  return 'altro';
}
function bianco(c) { return c && c[0] >= 225 && c[1] >= 225 && c[2] >= 225; }
function dentroBottone(el, card) {
  for (var e = el; e && e !== card; e = e.parentElement) {
    var tag = e.tagName;
    if (tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return true;
    if (e.getAttribute('role') === 'button') return true;
    if (e.classList && e.classList.contains('btn')) return true;
  }
  return false;
}
var cards = document.querySelectorAll(sel), n = 0;
for (var i = 0; i < cards.length; i++) {
  var card = cards[i], viste = [], fatte = [];
  var tutti = card.querySelectorAll('*');
  for (var j = 0; j < tutti.length; j++) {
    var el = tutti[j], proprio = '';
    for (var k = 0; k < el.childNodes.length; k++)
      if (el.childNodes[k].nodeType === 3) proprio += el.childNodes[k].textContent;
    if (!proprio.trim()) continue;
    var st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') continue;
    if (!bianco(rgba(st.color))) continue;
    if (dentroBottone(el, card)) continue;
    // il fondo colorato: quello dell'elemento o del primo contenitore (dentro la card)
    var box = null, bg = null;
    for (var e = el; e && e !== card.parentElement; e = e.parentElement) {
      bg = rgba(getComputedStyle(e).backgroundColor);
      if (bg) { box = e; break; }
    }
    if (!box || box === card || fatte.indexOf(box) >= 0) continue;
    var col = colore(bg);
    if (col !== 'verde' && col !== 'azzurro') continue;
    var testo = (box.innerText || box.textContent || '').replace(/\s+/g, ' ').trim();
    if (!testo || testo.length > 40) continue;
    if (/€|\bEUR\b/.test(testo)) continue;               // un prezzo, non un'etichetta
    fatte.push(box);
    viste.push([col, testo]);
  }
  card.setAttribute('data-vroomi-etichette',
    viste.map(function (v) { return v[1] + ' (' + v[0] + ')'; }).join(' | '));
  if (viste.length) n++;
  var nonPromo = viste.filter(function (v) { return !NONDISP.test(v[1]); });
  var verde = nonPromo.filter(function (v) { return v[0] === 'verde'; });
  var azz = nonPromo.filter(function (v) { return v[0] === 'azzurro'; });
  var scelta = verde.length ? verde[0] : (azz.length ? azz[0] : null);
  if (scelta) {
    card.setAttribute('data-vroomi-colore', scelta[0]);
    card.setAttribute('data-vroomi-etichetta', scelta[1]);
  }
}
return n;
"""


def _js() -> str:
    return "var NONDISP = new RegExp(%r, 'i');\n" % _NON_DISPONIBILITA_RE.pattern + ANNOTA_JS


def annota(driver, selector: str = CARD_SELECTOR) -> int:
    """Segna sulle card della pagina aperta in Chrome l'etichetta e il suo colore.
    Ritorna quante card hanno un'etichetta colorata (0 anche se il JavaScript fallisce:
    in quel caso leggi() usa il piano B su testo e classi)."""
    try:
        return int(driver.execute_script(_js(), selector) or 0)
    except Exception as e:  # mai fermare lo scraping per questo
        print(f"  [etichette] lettura colori non riuscita ({type(e).__name__}): "
              "uso testo e classi", flush=True)
        return 0


def _classi(el) -> str:
    return " ".join(el.get("class") or []).lower()


def leggi(card) -> tuple[str, str]:
    """(stato, testo dell'etichetta) di una card BeautifulSoup.
    stato = DISPONIBILE / NON_DISPONIBILE / SCONOSCIUTA."""
    colore = (card.get(ATTR_COLORE) or "").strip()
    testo = (card.get(ATTR_TESTO) or "").strip()
    if colore == "verde":
        return DISPONIBILE, testo
    if colore == "azzurro":
        return NON_DISPONIBILE, testo

    # Piano B (HTML senza i colori calcolati da Chrome): testo e classi delle etichette.
    for el in card.select(".availableOnText, .badge, .label, [class*='availab'], "
                          "[class*='disponib'], [class*='stock']"):
        t = " ".join(el.get_text(" ", strip=True).split())
        if not t or len(t) > 40 or _NON_DISPONIBILITA_RE.search(t):
            continue
        cls = _classi(el)
        if _TESTO_DISPONIBILE_RE.match(t) or re.search(r"success|green|verde", cls):
            return DISPONIBILE, t
        if "availableontext" in cls or re.search(r"\binfo\b|primary|blue|azzurr|-info|-primary", cls):
            return NON_DISPONIBILE, t
    return SCONOSCIUTA, ""


def descrivi(stato: str, testo: str) -> str:
    """Per i log: «Disponibile» (verde) / «Dal 17 Lug» (azzurra) / non trovata."""
    if stato == DISPONIBILE:
        return f"«{testo or 'Disponibile'}» (verde)"
    if stato == NON_DISPONIBILE:
        return f"«{testo or '?'}» (azzurra)"
    return "non trovata"
