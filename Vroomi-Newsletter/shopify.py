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

API_VERSION = "2025-07"   # productSet: prodotto + variante + costo + foto in una chiamata


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        # accetta valori tra virgolette doppie, singole o senza virgolette
        m = re.match(r"""\s*(?:export\s+)?([A-Z_]+)\s*=\s*(["']?)(.*?)\2\s*$""", line)
        if m:
            os.environ.setdefault(m.group(1), m.group(3))


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
        here = Path(__file__).parent
        _load_env(here / "credenziali.env")          # cartella da sola (zip per Giuliano)
        _load_env(here.parent / "credenziali.env")   # dentro automated-inventory
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
    def find_variant_by_sku(self, sku: str, barcode: str = "") -> dict | None:
        """{productId, title, status} se esiste gia' una variante con quello SKU
        (o, se dato, con quel barcode = ID MCWS)."""
        q = """
        query($q: String!) {
          productVariants(first: 5, query: $q) {
            nodes { sku barcode product { id title status } }
          }
        }"""
        checks = []
        if sku:
            checks.append((f"sku:{sku}", "sku", sku))
        if barcode:
            checks.append((f"barcode:{barcode}", "barcode", barcode))
        for query, field, value in checks:
            for n in self.gql(q, {"q": query})["productVariants"]["nodes"]:
                if (n.get(field) or "").upper() == value.upper():
                    return {"productId": n["product"]["id"], "title": n["product"]["title"],
                            "status": n["product"]["status"]}
        return None

    # ── creazione ────────────────────────────────────────────────────────────
    def create_draft_product(self, p: dict) -> dict:
        """Crea un prodotto DRAFT con 1 variante (sku, barcode, prezzo, costo,
        magazzino tracciato e non vendibile a quantità 0) e la foto, in un'unica
        chiamata productSet. `p` è il payload di run.build_payload."""
        mutation = """
        mutation($input: ProductSetInput!) {
          productSet(synchronous: true, input: $input) {
            product { id }
            userErrors { field message }
          }
        }"""
        variant = {
            "optionValues": [{"optionName": "Title", "name": "Default Title"}],
            "price": p["price"],
            "inventoryPolicy": "DENY",
            "taxable": True,
            "inventoryItem": {"sku": p["sku"], "tracked": True, "requiresShipping": True},
        }
        if p.get("barcode"):
            variant["barcode"] = p["barcode"]
        if p.get("cost"):
            variant["inventoryItem"]["cost"] = p["cost"]
        pin = {
            "title": p["title"],
            "vendor": p.get("vendor", ""),
            "productType": p.get("product_type", ""),
            "tags": p.get("tags", []),
            "descriptionHtml": p.get("description_html", ""),
            "status": "DRAFT",
            "metafields": p.get("metafields", []),
            "productOptions": [{"name": "Title", "values": [{"name": "Default Title"}]}],
            "variants": [variant],
        }
        if p.get("seo"):
            pin["seo"] = p["seo"]
        if p.get("image_url"):
            pin["files"] = [{"originalSource": p["image_url"], "contentType": "IMAGE",
                             "alt": p.get("image_alt", p["title"])[:255]}]
        res = self.gql(mutation, {"input": pin})["productSet"]
        if res["userErrors"]:
            raise RuntimeError(f"productSet: {res['userErrors']}")
        product_id = res["product"]["id"]
        return {"product_id": product_id, "admin_url": self.admin_url(product_id)}

    def admin_url(self, product_id: str) -> str:
        handle = self.domain.split(".")[0]   # es. scn8p4-h7 da scn8p4-h7.myshopify.com
        return f"https://admin.shopify.com/store/{handle}/products/{product_id.split('/')[-1]}"
