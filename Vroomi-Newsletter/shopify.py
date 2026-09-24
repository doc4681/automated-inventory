"""
shopify.py — client Admin API per creare schede prodotto DRAFT sullo store Vroomi.

Autenticazione: client credentials grant (SHOPIFY_CLIENT_ID/SECRET in ~/.env.vroomi),
stesso metodo di automated-inventory/shopify_enricher. Token valido ~24h.

Uso:
    sh = Shopify.from_env()
    if not sh.find_variant_by_sku(sku):
        sh.create_draft_product(payload)
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests

API_VERSION = "2024-10"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r'\s*(?:export\s+)?([A-Z_]+)\s*=\s*"?([^"]*)"?\s*$', line)
        if m:
            os.environ.setdefault(m.group(1), m.group(2))


def get_access_token(domain: str) -> str:
    static = os.environ.get("SHOPIFY_ADMIN_TOKEN", "").strip()
    if static:
        return static
    cid = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
    secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
    if not (cid and secret):
        raise RuntimeError("Credenziali Shopify mancanti (SHOPIFY_CLIENT_ID/SECRET).")
    resp = requests.post(
        f"https://{domain}/admin/oauth/access_token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"client_credentials fallito ({resp.status_code}): {resp.text[:300]}")
    tok = resp.json().get("access_token", "")
    if not tok:
        raise RuntimeError(f"Nessun access_token: {resp.text[:300]}")
    return tok


class Shopify:
    def __init__(self, domain: str, token: str):
        self.domain = domain
        self.url = f"https://{domain}/admin/api/{API_VERSION}/graphql.json"
        self.headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    @classmethod
    def from_env(cls) -> "Shopify":
        _load_env(Path(__file__).parent / "credenziali.env")  # file locale (portabile)
        _load_env(Path.home() / ".env.vroomi")
        domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "scn8p4-h7.myshopify.com").strip()
        return cls(domain, get_access_token(domain))

    def gql(self, query: str, variables: dict | None = None, retries: int = 5) -> dict:
        for attempt in range(retries):
            resp = requests.post(self.url, headers=self.headers,
                                 json={"query": query, "variables": variables or {}}, timeout=60)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                if any("throttl" in str(e).lower() for e in data["errors"]) and attempt < retries - 1:
                    time.sleep(2 ** attempt + 1)
                    continue
                raise RuntimeError(f"GraphQL errors: {data['errors']}")
            cost = data.get("extensions", {}).get("cost", {}).get("throttleStatus", {})
            if cost and cost.get("currentlyAvailable", 1000) < 200:
                time.sleep(1.0)
            return data["data"]
        raise RuntimeError("GraphQL: troppi retry (throttling)")

    # ── dedup ────────────────────────────────────────────────────────────────
    def find_variant_by_sku(self, sku: str) -> dict | None:
        """Ritorna {productId, title} se esiste gia' una variante con quello SKU."""
        if not sku:
            return None
        q = """
        query($q: String!) {
          productVariants(first: 1, query: $q) {
            nodes { sku product { id title status } }
          }
        }"""
        # lo SKU e' numerico: query esatta sku:'...'
        nodes = self.gql(q, {"q": f"sku:{sku}"})["productVariants"]["nodes"]
        for n in nodes:
            if (n.get("sku") or "") == sku:
                return {"productId": n["product"]["id"], "title": n["product"]["title"],
                        "status": n["product"]["status"]}
        return None

    # ── creazione ────────────────────────────────────────────────────────────
    def create_draft_product(self, p: dict) -> dict:
        """Crea un prodotto DRAFT con 1 variante e 1 immagine.
        `p` deve avere: title, vendor, product_type, tags[list], description_html,
                        sku, barcode, price(str), image_url."""
        create = """
        mutation($input: ProductInput!) {
          productCreate(input: $input) {
            product { id variants(first:1){ nodes { id } } }
            userErrors { field message }
          }
        }"""
        pin = {
            "title": p["title"],
            "vendor": p.get("vendor", ""),
            "productType": p.get("product_type", ""),
            "tags": p.get("tags", []),
            "descriptionHtml": p.get("description_html", ""),
            "status": "DRAFT",
        }
        if p.get("metafields"):
            pin["metafields"] = p["metafields"]
        res = self.gql(create, {"input": pin})["productCreate"]
        if res["userErrors"]:
            raise RuntimeError(f"productCreate: {res['userErrors']}")
        product_id = res["product"]["id"]
        variant_id = res["product"]["variants"]["nodes"][0]["id"]

        # variante: prezzo, sku, barcode
        upd = """
        mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            userErrors { field message }
          }
        }"""
        vin = {"id": variant_id, "price": p["price"]}
        if p.get("barcode"):
            vin["barcode"] = p["barcode"]
        if p.get("sku"):
            vin["inventoryItem"] = {"sku": p["sku"]}
        ures = self.gql(upd, {"productId": product_id, "variants": [vin]})["productVariantsBulkUpdate"]
        if ures["userErrors"]:
            raise RuntimeError(f"variantsBulkUpdate: {ures['userErrors']}")

        # immagine (Shopify la scarica dall'url pubblico)
        if p.get("image_url"):
            media = """
            mutation($productId: ID!, $media: [CreateMediaInput!]!) {
              productCreateMedia(productId: $productId, media: $media) {
                mediaUserErrors { field message }
              }
            }"""
            m = {"originalSource": p["image_url"], "mediaContentType": "IMAGE",
                 "alt": p["title"][:255]}
            mres = self.gql(media, {"productId": product_id, "media": [m]})["productCreateMedia"]
            if mres["mediaUserErrors"]:
                # non blocca: l'immagine si puo' aggiungere dopo
                print(f"    WARN immagine: {mres['mediaUserErrors']}", flush=True)

        return {"product_id": product_id, "admin_url":
                f"https://admin.shopify.com/store/vroomimodels/products/{product_id.split('/')[-1]}"}
