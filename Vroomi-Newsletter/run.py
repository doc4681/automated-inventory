"""
run.py — orchestratore: newsletter recenti di modelcarswholesale.com -> schede
prodotto DRAFT su Shopify (store Vroomi).

Flusso:
  1) login
  2) legge la sidebar 'newsletter recenti'
  3) tiene solo le newsletter il cui brand e' in Valid_Trademarks.txt e ha un markup
  4) apre ogni newsletter, fa scrape dei prodotti (+ pagina di dettaglio:
     materiale e nota -> metafield custom.material / custom.notes)
     e SALTA quelli con l'etichetta non «Disponibile» (azzurra invece di verde)
  5) prezzo Vroomi = costo (prezzo netto) * markup, arrotondato a .90
  6) dedup per SKU: salta i prodotti gia' presenti su Shopify
  7) crea la scheda in stato DRAFT (con --apply; altrimenti DRY-RUN)

Esempi:
  python run.py                          # DRY-RUN: mostra cosa farebbe, non scrive
  python run.py --newsletter 15149       # solo quella newsletter (MINICHAMPS)
  python run.py --newsletter 15149 --limit 1 --apply   # crea 1 solo DRAFT (test)
  python run.py --apply                  # elabora tutte le newsletter valide
  python run.py --apply --da-controllo output/da_creare_<data>.json
                                         # crea le bozze trovate da un controllo, SENZA
                                         # riaprire MCWS (niente Chrome, niente login)
"""

from __future__ import annotations

import re
import csv
import sys
import json
import argparse
import os
from datetime import datetime
from pathlib import Path

import etichette
import session
import scraper
import catalog
from shopify import Shopify

OUT = Path(__file__).parent / "output"


def quantita() -> int:
    """Quantità caricata a magazzino su ogni scheda nuova. Si cambia con
    NEWSLETTER_QUANTITA in credenziali.env (0 = non toccare il magazzino).
    Letta al momento dell'uso: credenziali.env viene caricato dopo l'import."""
    return int(os.environ.get("NEWSLETTER_QUANTITA", "1") or 0)

MSG_SCOPE_MAGAZZINO = (
    "Per caricare la quantità a magazzino l'app Shopify \"Vroomi Enricher_Claude\"\n"
    "deve avere anche gli scope  read_locations, read_inventory, write_inventory.\n"
    "Aggiungili su dev.shopify.com → app → Versions/Configuration → Access scopes,\n"
    "rilascia la nuova versione e approvala nel negozio, poi riprova.")
OUT.mkdir(exist_ok=True)

# Indizi da CORSA: campionati/gare/team/numero di gara. NON includere GT3/GT2/GTE
# da soli: compaiono nelle auto STRADALI (es. '911 GT3 RS COUPE'). Le vere racing
# hanno comunque TEAM, 'N <n>' o un evento (GP/24H/LE MANS/...).
RACING_RE = re.compile(
    r"\b(F1|F2|F3|GP|RALLY|WRC|DTM|NASCAR|WEC|LE MANS|24H|12H|6H|"
    r"IMSA|INDY|SUPERBIKE|TEAM|N \d+)\b", re.I)


def product_type_for(title: str) -> str:
    return "RACING CARS" if RACING_RE.search(title) else "ROAD CARS"


def scale_tag(scale: str) -> str:
    return scale.replace("/", ":") if scale else ""


_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def extract_year(text: str) -> str:
    m = _YEAR_RE.search(text or "")
    return m.group(1) if m else ""


def car_model_from(description: str) -> str:
    """Modello auto = testo prima dell'anno (in MAIUSCOLO). Es.
    '3.0 CSi E9 Coupe 1971 - Cerchi Alpina' -> '3.0 CSI E9 COUPE'.
    Senza anno: primo segmento prima di ' - '."""
    if not description:
        return ""
    m = _YEAR_RE.search(description)
    if m:
        head = description[:m.start()]
    else:
        head = description.split(" - ")[0]
    return head.strip(" -").upper()


# ── parsing racing (subcategory / event / driver / car_model corto) ───────────
ENDURANCE_RE = re.compile(
    r"\b(24H|12H|6H|LE MANS|LMGT|LMP|GT3|GT2|GTE|WEC|IMSA|DAYTONA|SEBRING|"
    r"SPA|NURBURGRING|BATHURST)\b", re.I)
F1_RE = re.compile(r"\bF1\b", re.I)
_NUM_RE = re.compile(r"\bN\s*\d+\b", re.I)          # 'N 23'
_PLACE_RE = re.compile(r"^\d+(?:st|nd|rd|th)\s+", re.I)   # '6th '
_CLASS_RE = re.compile(r"^[A-Z0-9]+\s+CLASS\s+", re.I)    # 'LMGT3 CLASS '
# cilindrata/motore da togliere dal car_model: '... P58 3.0L I6 TURBO' -> '... P58'
_ENGINE_RE = re.compile(r"\s+\d+(?:\.\d+)?L\b.*$", re.I)
_WS_RE = re.compile(r"\s{2,}")


def _clean(s: str) -> str:
    return _WS_RE.sub(" ", s or "").strip(" -").upper()


def _parse_race_segment(seg: str) -> tuple[str, str]:
    """'N 44 3rd BAHRAIN GP 2022 LEWIS HAMILTON' -> ('BAHRAIN GP 2022', 'LEWIS HAMILTON')"""
    m_year = _YEAR_RE.search(seg)
    if not m_year:
        return "", ""
    m_num = _NUM_RE.search(seg)
    start = m_num.end() if m_num and m_num.end() < m_year.start() else 0
    ev = seg[start:m_year.end()].strip()
    ev = _CLASS_RE.sub("", _PLACE_RE.sub("", ev))   # via '2nd ' e 'LMGT3 CLASS '
    return _clean(ev), _clean(seg[m_year.end():])


def parse_racing(description: str) -> dict:
    """Spezza la descrizione MCW di un modello da corsa. Formato tipico:
      '{MODELLO} TEAM {TEAM} N {NUM} [piazzamento] {EVENTO} {ANNO} {PILOTA} - {COLORE}'
    Es. 'F1 FW44 TEAM WILLIAMS RACING N 23 BAHRAIN GP 2022 ALEXANDER ALBON - BLUE'
      -> car_model 'F1 FW44', event 'BAHRAIN GP 2022', driver 'ALEXANDER ALBON'.
    I cofanetti ('SET 2X') hanno piu' auto unite da ' + ': eventi e piloti vengono
    raccolti da ogni segmento e uniti con ' - ' (senza duplicati).
    Euristica best-effort: i campi non riconosciuti restano vuoti."""
    out = {"car_model": "", "event": "", "driver": "", "subcategory": ""}
    if not description:
        return out

    if F1_RE.search(description):
        out["subcategory"] = "FORMULA 1"
    elif ENDURANCE_RE.search(description):
        out["subcategory"] = "ENDURANCE"

    # via il colore finale (ultimo ' - ')
    head = description.rsplit(" - ", 1)[0] if " - " in description else description

    # car_model = testo prima di ' TEAM ' o del numero di gara 'N <n>', senza
    # cilindrata (fallback: prima dell'anno). tail = resto, per event/driver.
    if " TEAM " in head:
        model_part, after = head.split(" TEAM ", 1)
        m_num = _NUM_RE.search(after)               # salta il nome del team
        tail = after[m_num.start():] if m_num else after
    else:
        m_num = _NUM_RE.search(head)
        model_part = head[:m_num.start()] if m_num else None
        tail = head[m_num.start():] if m_num else head
    out["car_model"] = _clean(_ENGINE_RE.sub("", model_part)) \
        if model_part is not None else car_model_from(description)

    # event/driver solo se c'e' un vero segnale di gara (TEAM o 'N <n>'): senza,
    # eviterei di trasformare 'MODELLO ANNO' (auto stradale) in un evento fittizio.
    if " TEAM " in head or _NUM_RE.search(tail):
        events, drivers = [], []
        for seg in tail.split(" + "):               # cofanetti: un segmento per auto
            ev, dr = _parse_race_segment(seg)
            if ev and ev not in events:
                events.append(ev)
            if dr and dr not in drivers:
                drivers.append(dr)
        out["event"] = " - ".join(events)
        out["driver"] = " - ".join(drivers)
    return out


def build_payload(p: scraper.Product, cat: catalog.Catalog) -> dict:
    vendor = cat.vendor_for(p.trademark)
    # Stesso formato dei prodotti già in negozio: "MARCA AUTO - DESCRIZIONE"
    title = f"{p.brand_auto} - {p.description}" if p.brand_auto else p.description
    ptype = product_type_for(title)
    stag = scale_tag(p.scale)

    # ── metafield (namespace custom) — le info vanno qui, non nella description ──
    year = extract_year(p.description)
    racing = parse_racing(p.description) if ptype == "RACING CARS" else {}
    car_model = racing.get("car_model") or car_model_from(p.description)
    subcat = racing.get("subcategory", "")

    tags = []
    subcat_tag = {"FORMULA 1": "F1", "ENDURANCE": "ENDURANCE"}.get(subcat, "")
    for t in [stag, p.brand_auto.upper(), vendor, ptype, subcat_tag]:
        if t and t not in tags:
            tags.append(t)

    TXT = "single_line_text_field"
    mf_pairs = [
        ("car_brand", p.brand_auto, TXT),
        ("car_model", car_model, TXT),
        ("category", ptype, TXT),
        ("subcategory", subcat, TXT),
        ("event", racing.get("event", ""), TXT),
        ("driver", racing.get("driver", ""), TXT),
        ("year", year, TXT),
        ("model_manufacturer", vendor, TXT),
        ("manufacturer", vendor, TXT),
        ("distributor", "MCWS", TXT),
        ("scale", stag, TXT),
        ("material", p.material.upper(), TXT),
        ("notes", p.note.upper(), TXT),
        ("availability", "no", TXT),
    ]
    metafields = [{"namespace": "custom", "key": k, "type": t, "value": v}
                  for k, v, t in mf_pairs if v]
    if stag:  # highlights = lista con la scala (come nell'esempio)
        metafields.append({"namespace": "custom", "key": "highlights",
                           "type": "list.single_line_text_field",
                           "value": json.dumps([stag])})

    markup = cat.markup_for(p.trademark)
    price = catalog.compute_price(p.cost, markup, tiers=cat.cost_tiers)
    nice = " ".join(w.capitalize() for w in f"{p.brand_auto} {car_model} {year}".split())

    return {
        "title": title,
        "vendor": vendor,
        "product_type": ptype,
        "tags": tags,
        "description_html": "-",          # come i prodotti Vroomi: info nei metafield
        "metafields": metafields,
        "sku": p.sku,
        "barcode": p.site_id,             # come i prodotti Vroomi: barcode = ID MCWS
        "quantity": quantita(),
        "price": f"{price:.2f}",
        "cost": f"{p.cost:.2f}",
        "seo": {"title": f"{nice} Scale Model Car",
                "description": f"{nice} scale model car. Detailed replica for collectors. "
                               "Available at Vroomi."},
        "image_url": p.image_url,
        "image_alt": f"{nice} {stag} scale model car by {vendor} — Vroomi",
        # meta per report
        "_cost": p.cost,
        "_markup": catalog.effective_markup(p.cost, markup, cat.cost_tiers),
        "_trademark": p.trademark,
        "_car_model": car_model,
        "_year": year,
        "_detail_url": p.detail_url,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="scrive davvero su Shopify (default: DRY-RUN)")
    ap.add_argument("--newsletter", help="elabora solo questa/e newsletter id (virgola-separate)")
    ap.add_argument("--limit", type=int, default=0, help="max prodotti da elaborare (0 = tutti)")
    ap.add_argument("--max-newsletters", type=int, default=0, help="max newsletter da elaborare")
    ap.add_argument("--no-enrich", action="store_true", help="non aprire la pagina di dettaglio")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--da-controllo", metavar="FILE",
                    help="con --apply: crea le bozze salvate da un controllo (non apre MCWS)")
    args = ap.parse_args()
    if args.da_controllo:
        if not args.apply:
            ap.error("--da-controllo va usato insieme a --apply")
        return create_from_check(Path(args.da_controllo))

    cat = catalog.Catalog()
    only_ids = set(x.strip() for x in args.newsletter.split(",")) if args.newsletter else None

    # client Shopify (serve per dedup anche in dry-run; se fallisce si continua senza)
    sh = None
    try:
        sh = Shopify.from_env()
        print("  [Shopify] token OK (store Vroomi)")
    except Exception as e:
        print(f"  [Shopify] non disponibile ({e}); dedup e creazione disattivati.")
        if args.apply:
            # Senza Shopify con --apply non verrebbe creato nulla: meglio fermarsi
            # subito con un errore chiaro che fare tutto lo scraping per niente.
            print("\nERRORE: con Shopify non disponibile non posso creare le schede.\n"
                  "Controlla SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET in credenziali.env.")
            sys.exit(1)

    if args.apply and sh is not None and quantita():
        # Controllo PRIMA dello scraping: se manca il permesso sul magazzino ci
        # si ferma subito, invece di creare schede a quantità 0.
        try:
            sh.location_id()
        except Exception as e:
            print(f"\nERRORE: non riesco a leggere il magazzino Shopify ({e}).\n"
                  + MSG_SCOPE_MAGAZZINO)
            sys.exit(1)

    if args.no_enrich:
        print("  [ATTENZIONE] --no-enrich: le pagine di dettaglio non vengono aperte,"
              " quindi MATERIALE e NOTE restano vuoti in questa anteprima.")

    bs = session.BrowserSession(headless=args.headless)
    report: list[dict] = []
    pending: list[dict] = []        # prodotti «da creare» del controllo (per --da-controllo)
    skipped_brands: list[tuple[str, str]] = []
    created = existing = no_price = no_markup = errors = 0
    processed = 0
    not_available: list[str] = []   # saltati: etichetta azzurra (non «Disponibile»)
    no_label: list[str] = []        # etichetta non trovata: processati come prima

    try:
        home = bs.get_soup(f"{session.BASE_URL}/it")
        newsletters = scraper.parse_sidebar(home)
        print(f"\nNewsletter in sidebar: {len(newsletters)}")

        # filtro brand
        kept = []
        for n in newsletters:
            if only_ids and n.id not in only_ids:
                continue
            if not cat.is_valid(n.brand):
                skipped_brands.append((f"{n.brand} (id {n.id})", "non in Valid_Trademarks"))
                continue
            if cat.markup_for(n.brand) is None:
                skipped_brands.append((f"{n.brand} (id {n.id})", "manca markup"))
                continue
            kept.append(n)

        # ID chiesti esplicitamente ma non presenti tra le newsletter "recenti"
        # della sidebar: prima venivano ignorati in silenzio (0 schede, nessun
        # messaggio). Ora si apre direttamente la pagina della newsletter e il
        # brand si verifica prodotto per prodotto.
        if only_ids:
            in_sidebar = {n.id for n in newsletters}
            for nid in sorted(only_ids - in_sidebar):
                if not nid:
                    continue
                print(f"  [info] newsletter {nid} non è tra le recenti della sidebar:"
                      " la apro direttamente.")
                kept.append(scraper.Newsletter(
                    id=nid, brand="", date="",
                    url=f"{session.BASE_URL}/it/newsletter/{nid}"))

        if args.max_newsletters:
            kept = kept[:args.max_newsletters]

        print(f"Newsletter valide da elaborare: {len(kept)}")
        for n in kept:
            print(f"  - {n.date or '?'} {n.brand or '(brand dai prodotti)'} (id {n.id})")
        if skipped_brands:
            print(f"Scartate ({len(skipped_brands)}): " +
                  ", ".join(f"{b}[{r}]" for b, r in skipped_brands[:20]))
        if not kept:
            print("\nNESSUNA newsletter da elaborare: non verrà creato nulla.")
            if only_ids:
                print("Gli ID indicati sono stati scartati (vedi 'Scartate' qui sopra):"
                      " il brand non è in Valid_Trademarks.txt o manca il markup"
                      " in Vroomi_Markup.txt.")

        # elaborazione
        for n in kept:
            soup = bs.get_soup(n.url)
            if soup is None:
                print(f"  !! {n.brand} ({n.id}): pagina non caricata")
                continue
            scarti: list = []
            prods = scraper.parse_newsletter(soup, scarti)
            print(f"\n== {n.brand or 'newsletter'} ({n.id}): {len(prods)} prodotti ==")
            for motivo, chi in scarti:
                print(f"  [NON LETTO — {motivo}] {chi}")
            # conteggio per newsletter: alla fine ogni prodotto della pagina ha un esito
            conto = {"da creare": 0, "creati": 0, "già nel negozio": 0, "non disponibili": 0,
                     "senza prezzo": 0, "marchio senza ricarico": 0, "errori": 0,
                     "non letti dalla pagina": len(scarti)}
            if prods and all(p.disponibilita == etichette.SCONOSCIUTA for p in prods):
                print("  [ATTENZIONE] nessuna etichetta di disponibilità trovata in questa "
                      "newsletter: il sito potrebbe essere cambiato. Processo tutti i prodotti.")

            for p in prods:
                if args.limit and processed >= args.limit:
                    break
                if p.disponibilita == etichette.NON_DISPONIBILE:
                    # Etichetta azzurra (non «Disponibile»): il prodotto si salta.
                    riga = (f"sku={p.sku}  etichetta {etichette.descrivi(p.disponibilita, p.etichetta)}"
                            f"  — {p.brand_auto} {p.description}  (newsletter {n.id})")
                    not_available.append(riga)
                    print(f"  [SALTATO — NON DISPONIBILE] {riga}")
                    report.append(_skipped_row(n, p, "SALTATO: NON DISPONIBILE"))
                    conto["non disponibili"] += 1
                    continue
                if p.disponibilita == etichette.SCONOSCIUTA:
                    no_label.append(f"sku={p.sku} (newsletter {n.id})")
                    print(f"  [etichetta non trovata: processo come prima] sku={p.sku}")
                if not p.cost:
                    no_price += 1
                    conto["senza prezzo"] += 1
                    print(f"  [SALTATO — SENZA PREZZO] sku={p.sku}  {p.brand_auto} {p.description}")
                    report.append(_skipped_row(n, p, "SALTATO: SENZA PREZZO"))
                    continue

                # markup del prodotto: il trademark scritto sul prodotto puo'
                # differire da quello della newsletter (es. 'MITICA-DIECAST' vs
                # 'MITICA'); in quel caso vale il brand della newsletter. Senza
                # markup il calcolo prezzo andava in crash (None * float).
                if (not n.brand and not cat.is_valid(p.trademark)) or (
                        cat.markup_for(p.trademark) is None
                        and not (n.brand and cat.markup_for(n.brand) is not None)):
                    no_markup += 1
                    conto["marchio senza ricarico"] += 1
                    print(f"  [SALTATO — MARCHIO NON VALIDO O SENZA RICARICO] sku={p.sku}"
                          f"  marchio={p.trademark}  {p.brand_auto} {p.description}")
                    report.append(_skipped_row(n, p, "SALTATO: MARCHIO SENZA RICARICO"))
                    continue
                if cat.markup_for(p.trademark) is None:
                    p.trademark = n.brand

                if not args.no_enrich:
                    det = bs.get_soup(p.detail_url)
                    if det is not None:
                        extra = scraper.parse_detail(det)
                        p.material = extra.get("material", "")
                        p.note = extra.get("note", "")

                payload = build_payload(p, cat)
                processed += 1

                status = "DRY-RUN"
                admin_url = ""
                if sh is not None:
                    dup = sh.find_variant_by_sku(p.sku, p.site_id)
                    if dup:
                        existing += 1
                        status = "ESISTE"
                        admin_url = sh.admin_url(dup["productId"])
                    elif args.apply:
                        try:
                            res = sh.create_draft_product(payload)
                            created += 1
                            status = "CREATO"
                            admin_url = res["admin_url"]
                        except Exception as e:
                            status = f"ERRORE: {e}"
                            errors += 1
                            if "ACCESS_DENIED" in str(e) or "access denied" in str(e).lower():
                                print(f"  [{status}]\n\nERRORE: permesso negato da Shopify.\n"
                                      + MSG_SCOPE_MAGAZZINO)
                                return 1
                    else:
                        status = "DA-CREARE"

                print(f"  [{status}] {payload['title'][:70]}")
                print(f"      sku={p.sku} costo={p.cost} x{payload['_markup']} -> €{payload['price']}"
                      f"  etichetta {etichette.descrivi(p.disponibilita, p.etichetta)}  {admin_url}")

                row = {
                    "newsletter_id": n.id, "brand": n.brand, "status": status,
                    "etichetta": p.etichetta, "site_id": p.site_id, "sku": p.sku,
                    "title": payload["title"],
                    "vendor": payload["vendor"], "scale": p.scale,
                    "car_model": payload["_car_model"], "year": payload["_year"],
                    "cost": p.cost, "markup": payload["_markup"], "price": payload["price"],
                    "material": p.material, "note": p.note,
                    "image_url": p.image_url, "detail_url": p.detail_url, "admin_url": admin_url,
                }
                report.append(row)
                if status in ("DA-CREARE", "DRY-RUN"):
                    pending.append({"payload": payload, "row": row})
                conto[{"ESISTE": "già nel negozio", "CREATO": "creati",
                       "DA-CREARE": "da creare", "DRY-RUN": "da creare"}.get(status, "errori")] += 1

            totale = sum(conto.values())
            print(f"  ── Newsletter {n.id}: {totale} prodotti sulla pagina → "
                  + ", ".join(f"{v} {k}" for k, v in conto.items() if v))
            if args.limit and processed >= args.limit:
                break
    finally:
        bs.quit()

    return _finish(report, processed=processed, created=created, existing=existing,
                   errors=errors, no_price=no_price, no_markup=no_markup, apply=args.apply,
                   pending=pending, not_available=not_available, no_label=no_label)


def _skipped_row(n, p, status: str) -> dict:
    """Riga del report per un prodotto della newsletter che non diventa bozza."""
    return {**dict.fromkeys(REPORT_FIELDS, ""),
            "newsletter_id": n.id, "brand": n.brand, "status": status,
            "etichetta": p.etichetta, "site_id": p.site_id, "sku": p.sku,
            "title": f"{p.brand_auto} - {p.description}", "vendor": p.trademark,
            "scale": p.scale, "cost": p.cost if p.cost else "",
            "image_url": p.image_url, "detail_url": p.detail_url}


# Colonne del report (i prodotti saltati hanno le stesse, in parte vuote)
REPORT_FIELDS = ["newsletter_id", "brand", "status", "etichetta", "site_id", "sku", "title",
                 "vendor", "scale", "car_model", "year", "cost", "markup", "price",
                 "material", "note", "image_url", "detail_url", "admin_url"]


def _finish(report: list, processed: int, created: int, existing: int, errors: int,
            no_price: int, no_markup: int, apply: bool, pending: list | None = None,
            not_available: list | None = None, no_label: list | None = None) -> int:
    """Scrive il report e il riepilogo finale (le righe che legge il pannello)."""
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    rep = OUT / f"report_{ts}.csv"
    if report:
        with open(rep, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=REPORT_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(report)
    if pending and not apply:
        # Il pannello li passa a «Crea le bozze» (--da-controllo): niente secondo login
        saved = OUT / f"da_creare_{ts}.json"
        saved.write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
        for old in sorted(OUT.glob("da_creare_*.json"))[:-10]:
            old.unlink(missing_ok=True)
        print(f"Da creare salvati: {saved}")

    print("\n" + "=" * 60)
    print(f"Prodotti elaborati (con prezzo): {processed}")
    print(f"  creati:   {created}")
    print(f"  esistenti (saltati): {existing}")
    print(f"  da creare (dry-run): {processed - created - existing - errors}")
    print(f"Prodotti senza prezzo (saltati): {no_price}")
    if no_markup:
        print(f"Prodotti di brand non validi / senza markup (saltati): {no_markup}")
    print(f"Saltati perché NON DISPONIBILI (etichetta azzurra, non «Disponibile»): "
          f"{len(not_available or [])}")
    for r in not_available or []:
        print(f"  - {r}")
    if no_label:
        print(f"Etichetta di disponibilità non trovata (processati come prima): {len(no_label)}")
        for r in no_label[:30]:
            print(f"  - {r}")
    if errors:
        print(f"ERRORI in creazione su Shopify: {errors} (dettaglio nel report)")
    if report:
        print(f"Report: {rep}")
    if not apply:
        print("\n[DRY-RUN] Nessuna scheda scritta. Aggiungi --apply per creare i DRAFT.")
    return 1 if errors else 0


MAX_CHECK_AGE_H = 48


def create_from_check(path: Path) -> int:
    """Crea le bozze salvate da un controllo (output/da_creare_*.json) senza riaprire
    MCWS: i dati delle schede sono già quelli mostrati dal controllo. Prima di creare
    ogni scheda ricontrolla su Shopify che non esista già (rilanciare è sicuro)."""
    if not path.exists():
        print(f"ERRORE: non trovo il controllo da usare ({path}): rifai «Controlla».")
        return 1
    age_h = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
    if age_h > MAX_CHECK_AGE_H:
        print(f"ERRORE: il controllo ha più di {MAX_CHECK_AGE_H} ore: rifai «Controlla» "
              "per avere prezzi e prodotti aggiornati.")
        return 1
    items = json.loads(path.read_text(encoding="utf-8"))
    print(f"Creo le bozze trovate dal controllo ({path.name}): {len(items)} prodotti.")
    print("  (uso i dati del controllo: non riapro modelcarswholesale.com, niente Chrome)")
    try:
        sh = Shopify.from_env()
        print("  [Shopify] token OK (store Vroomi)")
    except Exception as e:
        print(f"\nERRORE: Shopify non disponibile ({e}).\n"
              "Controlla SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET in credenziali.env.")
        return 1
    if any(it["payload"].get("quantity") for it in items):
        try:
            sh.location_id()
        except Exception as e:
            print(f"\nERRORE: non riesco a leggere il magazzino Shopify ({e}).\n"
                  + MSG_SCOPE_MAGAZZINO)
            return 1

    report: list[dict] = []
    created = existing = errors = 0
    for it in items:
        payload, row = it["payload"], dict(it["row"])
        dup = sh.find_variant_by_sku(row.get("sku", ""), row.get("site_id", ""))
        if dup:
            existing += 1
            row["status"], row["admin_url"] = "ESISTE", sh.admin_url(dup["productId"])
        else:
            try:
                res = sh.create_draft_product(payload)
                created += 1
                row["status"], row["admin_url"] = "CREATO", res["admin_url"]
            except Exception as e:
                errors += 1
                row["status"] = f"ERRORE: {e}"
                if "ACCESS_DENIED" in str(e) or "access denied" in str(e).lower():
                    print(f"  [{row['status']}]\n\nERRORE: permesso negato da Shopify.\n"
                          + MSG_SCOPE_MAGAZZINO)
                    return 1
        print(f"  [{row['status']}] {payload['title'][:70]}")
        print(f"      sku={row.get('sku')} -> €{payload['price']}  {row.get('admin_url', '')}")
        report.append(row)
    return _finish(report, processed=len(items), created=created, existing=existing,
                   errors=errors, no_price=0, no_markup=0, apply=True)

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrotto.")
        sys.exit(130)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nERRORE: il programma si è fermato ({type(e).__name__}: {e})")
        sys.exit(1)
