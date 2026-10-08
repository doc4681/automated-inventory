"""
verifica_etichette.py — controlla che l'etichetta di disponibilità venga letta giusta.

Apre Chrome (come newsletter e catalogo), legge le card con lo STESSO codice usato
dal programma (etichette.py, scraper newsletter, scraper carmodel) e dice per ogni
prodotto se verrebbe processato o saltato:

  • newsletter MCWS (default 15568): 4100643 → processato, 41006444 → saltato
  • marchio per l'inventario (default GP-REPLICAS, catalogo carmodel.com, la fonte
    delle etichette dell'inventario): GP184A → processato, GP12-48A → saltato
    + la stessa pagina marchio su modelcarswholesale.com, per confronto

Non scrive niente su Shopify. Il risultato è anche in logs/verifica_etichette_<data>.log.

Uso (dalla cartella principale, es. ~/Vroomi):
  .venv/bin/python pipeline/verifica_etichette.py
  .venv/bin/python pipeline/verifica_etichette.py --newsletter 15568 --nl-ok 4100643 --nl-no 41006444 \\
        --marchio GP-REPLICAS --inv-ok GP184A --inv-no GP12-48A
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "Vroomi-Newsletter"))     # in coda: chrome.py/paths.py di pipeline/

import carmodel_scraper  # noqa: E402
import etichette  # noqa: E402
import scraper as nl_scraper  # noqa: E402
import session as mcws_session  # noqa: E402

LOG = ROOT / "logs" / f"verifica_etichette_{datetime.now():%Y-%m-%d_%H%M%S}.log"
_lines: list[str] = []


def log(msg: str = "") -> None:
    print(msg, flush=True)
    _lines.append(msg)


def esito(stato: str) -> str:
    if stato == etichette.NON_DISPONIBILE:
        return "SALTATO"
    if stato == etichette.DISPONIBILE:
        return "processato"
    return "processato (etichetta non trovata!)"


def _key(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalnum())


def controlla(titolo: str, prodotti: list[tuple[str, str, str, str, str]],
              ok: list[str], no: list[str]) -> int:
    """prodotti = [(sku, stato, etichetta, descrizione, etichette viste sulla card)].
    Ritorna il numero di controlli sbagliati."""
    log(f"\n── {titolo}: {len(prodotti)} prodotti ──")
    for sku, stato, testo, descr, _viste in prodotti:
        segno = "⏭️ " if stato == etichette.NON_DISPONIBILE else "  "
        log(f"  {segno}{sku:<14} etichetta {etichette.descrivi(stato, testo):<28} → "
            f"{esito(stato):<10}  {descr[:50]}")
    saltati = [p for p in prodotti if p[1] == etichette.NON_DISPONIBILE]
    log(f"  Saltati (etichetta non «Disponibile»): {len(saltati)} — "
        + (", ".join(p[0] for p in saltati) or "nessuno"))
    errori = 0
    by_sku = {_key(p[0]): p for p in prodotti}
    for sku, atteso in [(s, etichette.DISPONIBILE) for s in ok] + [(s, etichette.NON_DISPONIBILE) for s in no]:
        p = by_sku.get(_key(sku))
        if p is None:
            log(f"  ❓ {sku}: non trovato in questa pagina")
            errori += 1
            continue
        giusto = p[1] == atteso
        errori += 0 if giusto else 1
        log(f"  {'✅ OK    ' if giusto else '❌ ERRORE'} {sku}: atteso "
            f"{'processato' if atteso == etichette.DISPONIBILE else 'SALTATO'}, "
            f"risulta {esito(p[1])} (etichetta {etichette.descrivi(p[1], p[2])})")
        if not giusto:
            log(f"           etichette colorate viste sulla card: {p[4] or 'nessuna'}")
    return errori


def newsletter(bs, nid: str, ok, no) -> int:
    soup = bs.get_soup(f"{mcws_session.BASE_URL}/it/newsletter/{nid}")
    if soup is None:
        log(f"\n❌ Newsletter {nid}: pagina non caricata")
        return 1
    return controlla(f"NEWSLETTER {nid} (modelcarswholesale.com)", _righe_mcws(soup), ok, no)


def _righe_mcws(soup) -> list:
    """Card MCWS (newsletter / pagina marchio) → righe per controlla(), senza doppioni."""
    righe, seen = [], set()
    for c in soup.select(etichette.CARD_SELECTOR):
        p = nl_scraper.parse_product_card(c)
        if p and p.site_id not in seen:
            seen.add(p.site_id)
            righe.append((p.sku, p.disponibilita, p.etichetta,
                          f"{p.brand_auto} {p.description}", c.get(etichette.ATTR_TUTTE, "")))
    return righe


def marchio_carmodel(driver, marchio: str, ok, no) -> int:
    prods = carmodel_scraper.scrape_trademark(driver, marchio)
    righe = [(p["codice_produttore"], p["disponibilita"], p["etichetta"],
              f"{p['brand_auto']} {p['titolo']}", "") for p in prods]
    return controlla(f"INVENTARIO — marchio {marchio} su carmodel.com (fonte delle etichette "
                     "dell'inventario)", righe, ok, no)


def marchio_mcws(bs, marchio: str, ok, no) -> None:
    """Solo per confronto: la stessa pagina marchio su modelcarswholesale.com."""
    url = f"{mcws_session.BASE_URL}/it/trademark/{marchio.lower().replace(' ', '-')}"
    try:
        soup = bs.get_soup(url)
    except Exception as e:
        log(f"\n(confronto MCWS non riuscito: {type(e).__name__})")
        return
    righe = _righe_mcws(soup) if soup is not None else []
    if not righe:
        log(f"\n(confronto: {url} non ha card prodotto leggibili)")
        return
    controlla(f"CONFRONTO — marchio {marchio} su modelcarswholesale.com (solo prima pagina)",
              righe, ok, no)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--newsletter", default="15568")
    ap.add_argument("--nl-ok", default="4100643", help="SKU che devono risultare disponibili")
    ap.add_argument("--nl-no", default="41006444", help="SKU che devono essere saltati")
    ap.add_argument("--marchio", default="GP-REPLICAS")
    ap.add_argument("--inv-ok", default="GP184A")
    ap.add_argument("--inv-no", default="GP12-48A")
    args = ap.parse_args()
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]  # noqa: E731

    log("════════════════════════════════════════════════════════")
    log(f"VERIFICA ETICHETTE DI DISPONIBILITÀ — {datetime.now():%d/%m/%Y %H:%M}")
    log("Verde «Disponibile» → processato · azzurra (altro testo) → SALTATO")
    log("════════════════════════════════════════════════════════")

    errori = 0
    bs = mcws_session.BrowserSession()
    try:
        errori += newsletter(bs, args.newsletter, split(args.nl_ok), split(args.nl_no))
        errori += marchio_carmodel(bs.drv, args.marchio, split(args.inv_ok), split(args.inv_no))
        marchio_mcws(bs, args.marchio, split(args.inv_ok), split(args.inv_no))
    finally:
        bs.quit()

    log("\n════════════════════════════════════════════════════════")
    log("✅ VERIFICA SUPERATA" if not errori else f"❌ VERIFICA NON SUPERATA: {errori} controlli sbagliati")
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    log(f"Registro: {LOG}")
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(main())
