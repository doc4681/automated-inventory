"""
shopify_enricher.py
4° stadio (OPZIONALE) della pipeline: scrive il campo `note` del catalogo merged
nel metafield Shopify `custom.notes` dei prodotti corrispondenti.

Sorgenti delle note (in quest'ordine, vince la prima nota NON vuota):
  1) merged_products_*.csv   (catalogo unito carmodel+MCWS)
  2) carmodel_scraped_*.csv  (scrape grezzo: contiene anche i prodotti che il
     merge scarta perche' non presenti nella stock list MCWS — senza questo
     fallback l'enricher saltava centinaia di prodotti)

Match prodotto store ⇄ catalogo:
  1) EAN (catalogo)  == barcode (variante Shopify)   [chiave primaria]
  2) codice_produttore (catalogo) == SKU (variante)  [fallback, normalizzato alfanumerico]

REGOLA D'ORO — questo script ARRICCHISCE, non sostituisce e non cancella:
  * scrive la nota SOLO sui prodotti che su Shopify non ce l'hanno (o ce l'hanno vuota);
  * non cancella MAI un metafield esistente;
  * se il prodotto ha gia' una nota diversa la lascia com'e' (la segnala e basta).
  Le eccezioni vanno chieste esplicitamente:
     --overwrite      aggiorna anche le note gia' presenti ma diverse dal catalogo
     --allow-delete   cancella la nota quando il catalogo ce l'ha vuota  [PERICOLOSO]
I prodotti store NON presenti nel catalogo non vengono toccati in nessun caso.

Credenziali (env, in ~/.env.vroomi). Due modi:
  A) Dev Dashboard (consigliato, post-2026) — client credentials grant:
       SHOPIFY_CLIENT_ID       Client ID dell'app (dalla Dev Dashboard)
       SHOPIFY_CLIENT_SECRET   Client secret (shpss_...) della stessa app
     Lo script ottiene da solo un token Admin (shpat_, valido 24h) ad ogni run.
  B) Token statico (app legacy, pre-2026):
       SHOPIFY_ADMIN_TOKEN     token Admin API (shpat_...)
  In entrambi i casi:
       SHOPIFY_STORE_DOMAIN    es. scn8p4-h7.myshopify.com   (default sotto)
  L'app deve avere gli scope: read_products, write_products.

Uso:
  python pipeline/shopify_enricher.py            # DRY-RUN (non scrive nulla)
  python pipeline/shopify_enricher.py --apply    # scrive davvero su Shopify
  python pipeline/shopify_enricher.py --apply --limit 50   # solo primi 50 (test)
"""

from __future__ import annotations  # compatibilità Python 3.9 (sintassi "X | None")

import os
import sys
import csv
import time
import json
import argparse
from datetime import datetime
from pathlib import Path

import requests

API_VERSION = "2024-10"
NAMESPACE = "custom"
KEY = "notes"
MF_TYPE = "single_line_text_field"

from paths import CARMODEL_DIR, MERGED_DIR, RESULT_LATEST, latest_file


def log(msg: str) -> None:
    print(msg, flush=True)


# ── Input merged CSV (stesso pattern del merger) ─────────────────────────────
def resolve_merged() -> Path:
    ts = os.environ.get("RUN_TIMESTAMP", "")
    exact = MERGED_DIR / f"merged_products_{ts}.csv"
    if ts and exact.exists():
        return exact
    if RESULT_LATEST.exists():
        return RESULT_LATEST
    latest = latest_file(MERGED_DIR, "merged_products")
    if latest:
        return latest
    raise SystemExit(
        "ERRORE: nessun catalogo trovato (merged_products_*.csv).\n"
        "        Lancia prima 'AGGIORNA INVENTARIO': le note arrivano da li'.")


def norm_sku(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _rows(path: Path) -> int:
    with open(path, newline="", encoding="utf-8") as f:
        return max(sum(1 for _ in f) - 1, 0)


def resolve_scraped(min_rows: int) -> Path | None:
    """Scrape grezzo carmodel (sorgente vera delle note). None se non c'è.

    Attenzione: in dati/carmodel restano anche i file di run parziali/di prova.
    Il merge e' un sottoinsieme dello scrape, quindi uno scrape valido ha almeno
    tante righe quante il catalogo merged: i file piu' piccoli vengono scartati,
    altrimenti l'enricher userebbe un catalogo mutilato e salterebbe prodotti.
    """
    out = CARMODEL_DIR
    ts = os.environ.get("RUN_TIMESTAMP", "")
    exact = out / f"carmodel_scraped_{ts}.csv"
    if ts and exact.exists():
        return exact
    cands = sorted(out.glob("carmodel_scraped_*.csv"), key=lambda f: f.stat().st_mtime,
                   reverse=True)
    for c in cands:
        if _rows(c) >= min_rows:
            return c
        log(f"  [scrape] ignoro {c.name}: {_rows(c)} righe < {min_rows} del merged (run parziale)")
    return None


# Stessa regola del merger: queste note non vanno pubblicate.
EXCLUDE_NOTE_PHRASE = "EXCLUSIVE CARMODEL"


def clean_note(note: str) -> str:
    note = (note or "").strip()
    return "" if EXCLUDE_NOTE_PHRASE in note.upper() else note


def _put(d: dict, key: str, note: str) -> None:
    """Indicizza senza perdere informazione: una nota piena non viene mai
    sovrascritta da una vuota (stesso codice presente in piu' sorgenti)."""
    if not key:
        return
    if note or key not in d:
        d[key] = note


def load_catalog(merged: Path, scraped: Path | None) -> tuple[dict, dict]:
    """Ritorna (ean_to_note, sku_to_note) unendo catalogo merged + scrape grezzo.
    La nota può essere stringa vuota (= il prodotto esiste ma non ha note)."""
    ean_to_note, sku_to_note = {}, {}
    for r in csv.DictReader(open(merged, newline="", encoding="utf-8")):
        note = clean_note(r.get("note"))
        _put(ean_to_note, (r.get("ean") or "").strip(), note)
        _put(sku_to_note, norm_sku((r.get("codice_produttore") or "").strip()), note)
    if scraped is not None:
        # il merge tiene solo l'intersezione con la stock list MCWS: qui recuperiamo
        # le note dei prodotti carmodel che il merge ha scartato.
        for r in csv.DictReader(open(scraped, newline="", encoding="utf-8")):
            _put(sku_to_note, norm_sku((r.get("codice_produttore") or "").strip()),
                 clean_note(r.get("note")))
    return ean_to_note, sku_to_note


# ── Auth: ottieni un access token Admin (client credentials grant) ───────────
def get_access_token(domain: str) -> str:
    """Ritorna un token Admin API. Priorità:
    1) SHOPIFY_ADMIN_TOKEN se presente (token statico legacy)
    2) client credentials grant con SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET
       (Dev Dashboard, app installata nel proprio negozio)."""
    static = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
    if static:
        return static

    cid = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
    secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
    if not (cid and secret):
        raise SystemExit(
            "ERRORE: nessuna credenziale Shopify. Imposta in ~/.env.vroomi:\n"
            "  SHOPIFY_CLIENT_ID=...\n  SHOPIFY_CLIENT_SECRET=shpss_...\n"
            "  (oppure SHOPIFY_ADMIN_TOKEN=shpat_... per un'app legacy)")

    resp = requests.post(
        f"https://{domain}/admin/oauth/access_token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret},
        timeout=30,
    )
    if resp.status_code != 200:
        raise SystemExit(f"ERRORE client_credentials ({resp.status_code}): {resp.text[:300]}")
    tok = resp.json().get("access_token", "")
    if not tok:
        raise SystemExit(f"ERRORE: nessun access_token nella risposta: {resp.text[:300]}")
    log("Token Admin ottenuto via client credentials (valido ~24h).")
    return tok


# ── Shopify Admin API ────────────────────────────────────────────────────────
class Shopify:
    def __init__(self, domain: str, token: str):
        self.url = f"https://{domain}/admin/api/{API_VERSION}/graphql.json"
        self.headers = {"X-Shopify-Access-Token": token,
                        "Content-Type": "application/json"}

    def gql(self, query: str, variables: dict | None = None, retries: int = 5) -> dict:
        for attempt in range(retries):
            resp = requests.post(self.url, headers=self.headers,
                                 json={"query": query, "variables": variables or {}},
                                 timeout=60)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                throttled = any("throttl" in str(e).lower() for e in data["errors"])
                if throttled and attempt < retries - 1:
                    time.sleep(2 ** attempt + 1)
                    continue
                raise RuntimeError(f"GraphQL errors: {data['errors']}")
            # throttle preventivo se i punti residui sono bassi
            cost = data.get("extensions", {}).get("cost", {})
            ts = cost.get("throttleStatus", {})
            if ts and ts.get("currentlyAvailable", 1000) < 200:
                time.sleep(1.0)
            return data["data"]
        raise RuntimeError("GraphQL: troppi retry (throttling)")

    def iter_products(self, page_size: int = 200):
        q = """
        query($cursor: String) {
          products(first: %d, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id
              notes: metafield(namespace: "%s", key: "%s") { id value }
              variants(first: 10) { nodes { sku barcode } }
            }
          }
        }""" % (page_size, NAMESPACE, KEY)
        cursor = None
        while True:
            data = self.gql(q, {"cursor": cursor})
            conn = data["products"]
            for node in conn["nodes"]:
                yield node
            if conn["pageInfo"]["hasNextPage"]:
                cursor = conn["pageInfo"]["endCursor"]
            else:
                break


SET_MUTATION = """
mutation($mf: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $mf) {
    metafields { id }
    userErrors { field message }
  }
}"""

DEL_MUTATION = """
mutation($ids: [MetafieldIdentifierInput!]!) {
  metafieldsDelete(metafields: $ids) {
    deletedMetafields { ownerId key namespace }
    userErrors { field message }
  }
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="scrive davvero (default: dry-run)")
    ap.add_argument("--limit", type=int, default=0, help="processa solo N prodotti (test)")
    ap.add_argument("--overwrite", action="store_true",
                    help="aggiorna anche le note già presenti ma diverse dal catalogo "
                         "(default: le note esistenti NON si toccano)")
    ap.add_argument("--allow-delete", action="store_true",
                    help="PERICOLOSO: cancella la nota su Shopify quando il catalogo "
                         "ce l'ha vuota (default: non cancella mai nulla)")
    args = ap.parse_args()

    domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "scn8p4-h7.myshopify.com")
    token = get_access_token(domain)

    merged = resolve_merged()
    scraped = resolve_scraped(_rows(merged))
    ean_to_note, sku_to_note = load_catalog(merged, scraped)
    log(f"Catalogo merged : {merged.name}")
    log(f"Scrape carmodel : {scraped.name if scraped else '— (assente: alcune note non saranno disponibili)'}")
    log(f"Indicizzati     : EAN {len(ean_to_note)}  SKU {len(sku_to_note)}")
    log(f"Modalità        : {'APPLY (scrive)' if args.apply else 'DRY-RUN (nessuna scrittura)'}"
        f"{'  +overwrite' if args.overwrite else ''}"
        f"{'  +allow-delete' if args.allow_delete else ''}")

    sh = Shopify(domain, token)

    to_set, to_delete = [], []
    kept, changed_skipped = [], []
    n_products = n_matched = n_nochange = 0

    for node in sh.iter_products():
        n_products += 1
        if args.limit and n_products > args.limit:
            n_products -= 1
            break

        # Nota desiderata: si raccolgono TUTTI i candidati (EAN e SKU di ogni
        # variante) e vince la prima nota NON vuota. Con il vecchio "primo match
        # e basta" un EAN senza nota nascondeva la nota trovabile via SKU.
        found = False
        desired = ""
        for v in node["variants"]["nodes"]:
            for idx, key in ((ean_to_note, (v.get("barcode") or "").strip()),
                             (sku_to_note, norm_sku(v.get("sku") or ""))):
                if key and key in idx:
                    found = True
                    if idx[key]:
                        desired = idx[key]
                        break
            if desired:
                break
        if not found:
            continue  # prodotto non nel catalogo → non toccare

        n_matched += 1
        current = (node["notes"]["value"] if node.get("notes") else None)
        cur_txt = (current or "").strip()

        if desired and not cur_txt:
            # caso normale dell'arricchimento: il prodotto non ha nota, gliela mettiamo
            to_set.append({"ownerId": node["id"], "namespace": NAMESPACE,
                           "key": KEY, "type": MF_TYPE, "value": desired})
        elif desired and cur_txt != desired:
            # nota già presente e diversa: NON si sovrascrive (a meno di --overwrite)
            if args.overwrite:
                to_set.append({"ownerId": node["id"], "namespace": NAMESPACE,
                               "key": KEY, "type": MF_TYPE, "value": desired})
            else:
                changed_skipped.append((node["id"], cur_txt, desired))
        elif not desired and cur_txt:
            # il catalogo non ha nota ma il prodotto sì (spesso inserita a mano):
            # si CONSERVA. Cancella solo se richiesto esplicitamente.
            if args.allow_delete:
                to_delete.append({"ownerId": node["id"], "namespace": NAMESPACE, "key": KEY})
            else:
                kept.append((node["id"], cur_txt))
        else:
            n_nochange += 1

    log(f"\nProdotti store esaminati : {n_products}")
    log(f"Match col catalogo       : {n_matched}")
    log(f"Già a posto (skip)       : {n_nochange}")
    log(f"Da scrivere (set)        : {len(to_set)}")
    log(f"Note esistenti CONSERVATE: {len(kept)}"
        f"{' (--allow-delete le cancellerebbe)' if kept else ''}")
    log(f"Note diverse NON toccate : {len(changed_skipped)}"
        f"{' (usa --overwrite per aggiornarle)' if changed_skipped else ''}")
    log(f"Da cancellare (delete)   : {len(to_delete)}")
    for pid, cur in kept[:10]:
        log(f"    conservata  {pid.split('/')[-1]}: {cur[:50]!r}")
    for pid, cur, des in changed_skipped[:10]:
        log(f"    invariata   {pid.split('/')[-1]}: {cur[:40]!r}  (catalogo: {des[:40]!r})")

    if not args.apply:
        log("\nDRY-RUN: nessuna modifica applicata. Esempi (primi 5 set):")
        for m in to_set[:5]:
            log(f"  {m['ownerId'].split('/')[-1]} ← {m['value'][:50]!r}")
        log("\nRilancia con --apply per scrivere su Shopify.")
        return

    # ── Applica in batch da 25 ───────────────────────────────────────────────
    errors = 0

    def chunks(lst, n=25):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    written = 0
    for batch in chunks(to_set):
        data = sh.gql(SET_MUTATION, {"mf": batch})
        ue = data["metafieldsSet"]["userErrors"]
        if ue:
            errors += len(ue)
            log(f"  userErrors set: {ue[:3]}")
        written += len(batch) - len(ue)
        log(f"  set: {written}/{len(to_set)}")

    deleted = 0
    for batch in chunks(to_delete):
        data = sh.gql(DEL_MUTATION, {"ids": batch})
        ue = data["metafieldsDelete"]["userErrors"]
        if ue:
            errors += len(ue)
            log(f"  userErrors delete: {ue[:3]}")
        deleted += len(batch) - len(ue)
        log(f"  delete: {deleted}/{len(to_delete)}")

    log(f"\nFatto. Scritti: {written}  Cancellati: {deleted}  Errori: {errors}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
