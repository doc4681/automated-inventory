"""
shopify_enricher.py
4° stadio (OPZIONALE) della pipeline: scrive il campo `note` del catalogo merged
nel metafield Shopify `custom.notes` dei prodotti corrispondenti.

Match prodotto store ⇄ catalogo:
  1) EAN (catalogo)  == barcode (variante Shopify)   [chiave primaria]
  2) codice_produttore (catalogo) == SKU (variante)  [fallback, normalizzato alfanumerico]

Scope di scrittura: TUTTI i prodotti store che matchano il catalogo (overwrite, anche
vuoto → se la nota è vuota e il prodotto ha già un valore, il metafield viene CANCELLATO).
I prodotti store NON presenti nel catalogo non vengono toccati.

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
  python shopify_enricher/shopify_enricher.py            # DRY-RUN (non scrive nulla)
  python shopify_enricher/shopify_enricher.py --apply    # scrive davvero su Shopify
  python shopify_enricher/shopify_enricher.py --apply --limit 50   # solo primi 50 (test)
"""

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

ROOT = Path(__file__).parent.parent


def log(msg: str) -> None:
    print(msg, flush=True)


# ── Input merged CSV (stesso pattern del merger) ─────────────────────────────
def resolve_merged() -> Path:
    ts = os.environ.get("RUN_TIMESTAMP", "")
    exact = ROOT / "merger" / "output" / f"merged_products_{ts}.csv"
    if ts and exact.exists():
        return exact
    latest = ROOT / "RISULTATO" / "merged_products_LATEST.csv"
    if latest.exists():
        return latest
    cands = sorted((ROOT / "merger" / "output").glob("merged_products_*.csv"),
                   key=lambda f: f.stat().st_mtime)
    if cands:
        return cands[-1]
    raise FileNotFoundError("Nessun file merged_products trovato.")


def norm_sku(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalnum())


def load_catalog(path: Path) -> tuple[dict, dict]:
    """Ritorna (ean_to_note, sku_to_note). note può essere stringa vuota."""
    ean_to_note, sku_to_note = {}, {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            note = (r.get("note") or "").strip()
            ean = (r.get("ean") or "").strip()
            cod = (r.get("codice_produttore") or "").strip()
            if ean:
                ean_to_note[ean] = note
            if cod:
                sku_to_note[norm_sku(cod)] = note
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
    args = ap.parse_args()

    domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "scn8p4-h7.myshopify.com")
    token = get_access_token(domain)

    merged = resolve_merged()
    ean_to_note, sku_to_note = load_catalog(merged)
    log(f"Catalogo: {merged.name}  | EAN indicizzati: {len(ean_to_note)}  SKU: {len(sku_to_note)}")
    log(f"Modalità: {'APPLY (scrive)' if args.apply else 'DRY-RUN (nessuna scrittura)'}")

    sh = Shopify(domain, token)

    to_set, to_delete = [], []
    n_products = n_matched = n_nochange = 0

    for node in sh.iter_products():
        n_products += 1
        if args.limit and n_products > args.limit:
            n_products -= 1
            break

        # nota desiderata dal catalogo (EAN poi SKU)
        desired = None
        for v in node["variants"]["nodes"]:
            bc = (v.get("barcode") or "").strip()
            if bc and bc in ean_to_note:
                desired = ean_to_note[bc]
                break
        if desired is None:
            for v in node["variants"]["nodes"]:
                sk = norm_sku(v.get("sku") or "")
                if sk and sk in sku_to_note:
                    desired = sku_to_note[sk]
                    break
        if desired is None:
            continue  # prodotto non nel catalogo → non toccare

        n_matched += 1
        current = (node["notes"]["value"] if node.get("notes") else None)

        if desired:  # nota non vuota
            if desired != current:
                to_set.append({"ownerId": node["id"], "namespace": NAMESPACE,
                               "key": KEY, "type": MF_TYPE, "value": desired})
            else:
                n_nochange += 1
        else:        # nota vuota → cancella metafield se presente
            if current is not None:
                to_delete.append({"ownerId": node["id"], "namespace": NAMESPACE, "key": KEY})
            else:
                n_nochange += 1

    log(f"\nProdotti store esaminati : {n_products}")
    log(f"Match col catalogo       : {n_matched}")
    log(f"Già allineati (skip)     : {n_nochange}")
    log(f"Da scrivere (set)        : {len(to_set)}")
    log(f"Da cancellare (delete)   : {len(to_delete)}")

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
