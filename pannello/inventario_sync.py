"""
inventario_sync.py — "Aggiorna l'inventario" in automatico, senza caricare file.

  1. legge i prodotti DIRETTAMENTE da Shopify (Admin API, stesse credenziali
     dello strumento newsletter) al posto dell'export Products.csv
  2. listino MCWS: l'ultimo scaricato dal catalogo automatico (dati/mcws/),
     oppure ne scarica uno nuovo adesso (--mcws-nuovo, si apre Chrome)
  3. giacenze BBR: l'ultimo file caricato nel pannello (dati/bbr/), facoltativo
  4. calcola le modifiche con la stessa logica di sempre (logic_v03.py); i prodotti MCWS
     con l'etichetta non «Disponibile» (scritta bianca su azzurro invece che su verde)
     si saltano e si elencano nel log. L'etichetta viene dall'ultimo catalogo carmodel
     (dati/carmodel/, colonna «disponibilita», la salva pipeline/carmodel_scraper.py)
  5. con --apply le scrive su Shopify: quantità, costo, prezzo, prezzo barrato, tag SALE
     (con --solo-disponibilita solo la quantità; con --solo-prezzi niente listini, solo i prezzi)

La quantità si scrive SEMPRE nella sede di magazzino «Vroomi Models» (Shopify.location_id).
Se un prodotto ha merce anche in altre sedi (es. quella del rappresentante fiscale), quando
lo si aggiorna la merce viene spostata tutta su Vroomi Models (le altre sedi vanno a 0):
il controllo li conta come «spostati su Vroomi Models».

Senza --apply non scrive niente su Shopify (è il "Controlla").
Protezione: se troppi prodotti diventerebbero esauriti (listino sbagliato o
incompleto) --apply si ferma, a meno di --forza.

Uso (dalla cartella principale):
  .venv/bin/python -m pannello.inventario_sync                 # controllo
  .venv/bin/python -m pannello.inventario_sync --apply         # applica
  opzioni: --solo-prezzi  --solo-disponibilita  --mcws-nuovo  --mcws FILE  --bbr FILE  --senza-bbr  --forza
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "Vroomi-Newsletter"))   # client Shopify condiviso

from pannello.logic_v03 import (  # noqa: E402
    COL_CHANGE_LOG, COL_COMPARE, COL_COST, COL_PRICE, COL_QTY, COL_SKU, COL_TAGS,
    LABEL_NOT_AVAILABLE, clean_currency, clean_qty, match_key, normalize_string,
    process_availability_only, process_inventory_v03, process_markup_only,
)
from shopify import LOCATION_NAME, Shopify, _load_env  # noqa: E402

DATA_DIR = REPO / "dati"
MCWS_DIR = DATA_DIR / "mcws"
CARMODEL_DIR = DATA_DIR / "carmodel"     # etichette di disponibilità (catalogo carmodel)
BBR_DIR = DATA_DIR / "bbr"
REPORT_DIR = DATA_DIR / "inventario"
REJECTED_DIR = DATA_DIR / "scartati"
TRADEMARKS_FILE = REPO / "config" / "Valid_Trademarks.txt"
MARKUP_FILE = REPO / "config" / "Vroomi_Markup.txt"
PIPELINE_LOCK_PID = REPO / "logs" / ".run.lock" / "pid"

MIN_MCWS_ROWS = 1000        # come pipeline/run.sh
MAX_DROP_PCT = 50           # listino nuovo con meno della metà delle righe del precedente = sospetto
MAX_OUT_OF_STOCK_PCT = 30   # oltre questa quota di disponibili che diventano esauriti, --apply si ferma
MIN_OUT_OF_STOCK_BLOCK = 20
LABELS_OLD_DAYS = 4         # etichette più vecchie di così: avviso nel log
KEEP_REPORTS = 15

# Colonne del "Products.csv" ricostruito da Shopify (+ ID interni, che iniziano con _).
COL_HANDLE, COL_TITLE, COL_VENDOR, COL_STATUS = "Handle", "Title", "Vendor", "Status"
COL_BARCODE = "Variant Barcode"
COL_RESULT, COL_URL = "Esito", "Su Shopify"
REPORT_COLUMNS = [COL_HANDLE, COL_TITLE, COL_VENDOR, COL_STATUS, COL_TAGS, COL_SKU, COL_BARCODE,
                  COL_QTY, COL_COST, COL_PRICE, COL_COMPARE, COL_CHANGE_LOG, COL_RESULT, COL_URL]


def log(msg: str = "") -> None:
    print(msg, flush=True)


# ─────────────────────────── Lettura file ────────────────────────────────────
def read_table(path: Path) -> pd.DataFrame:
    """CSV (virgola o punto e virgola) o Excel, tutto come testo."""
    if path.suffix.lower() in (".xls", ".xlsx"):
        return pd.read_excel(path, dtype=str)
    df = pd.read_csv(path, dtype=str)
    if len(df.columns) == 1:            # separatore ';' (export italiani)
        df = pd.read_csv(path, dtype=str, sep=";")
    return df


def csv_rows(path: Path) -> int:
    with open(path, encoding="utf-8", errors="replace") as f:
        return max(sum(1 for _ in f) - 1, 0)


def latest(directory: Path, pattern: str) -> Path | None:
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime) if directory.exists() else []
    return files[-1] if files else None


def _age(path: Path) -> str:
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    days = (datetime.now() - mtime).days
    return f"del {mtime:%d/%m/%Y %H:%M}" + (f", {days} giorni fa" if days else "")


# ─────────────────────────── Listino MCWS ────────────────────────────────────
def _pipeline_running() -> bool:
    try:
        os.kill(int(PIPELINE_LOCK_PID.read_text().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def download_mcws() -> Path | None:
    """Scarica adesso il listino MCWS (stesso downloader del catalogo automatico).
    Ritorna il file solo se sembra completo; altrimenti None (e lo sposta in dati/scartati/)."""
    if _pipeline_running():
        log("  L'aggiornamento del catalogo è in corso e sta già scaricando il listino: "
            "uso l'ultimo disponibile.")
        return None
    previous = latest(MCWS_DIR, "mcws_inventory_*.csv")
    env = os.environ.copy()
    env["RUN_TIMESTAMP"] = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    env["PYTHONUNBUFFERED"] = "1"
    out = MCWS_DIR / f"mcws_inventory_{env['RUN_TIMESTAMP']}.csv"
    log("  Scarico il listino da modelcarswholesale.com (si apre Chrome: non chiuderlo)…")
    subprocess.run([sys.executable, "-u", str(REPO / "pipeline" / "mcws_downloader.py")],
                   cwd=str(REPO), env=env)
    if not out.exists():
        log("  ✗ Download del listino MCWS non riuscito.")
        return None
    rows, prev_rows = csv_rows(out), (csv_rows(previous) if previous else 0)
    problem = ""
    if rows < MIN_MCWS_ROWS:
        problem = f"solo {rows} righe (minimo {MIN_MCWS_ROWS})"
    elif prev_rows and rows * 100 < prev_rows * (100 - MAX_DROP_PCT):
        problem = f"{rows} righe contro {prev_rows} del precedente"
    if problem:
        REJECTED_DIR.mkdir(parents=True, exist_ok=True)
        out.rename(REJECTED_DIR / out.name)
        log(f"  ✗ Listino scaricato sospetto ({problem}): scartato.")
        return None
    log(f"  ✓ Listino nuovo: {rows} righe.")
    return out


def resolve_mcws(arg: str | None, fresh: bool) -> Path:
    if arg:
        return Path(arg)
    if fresh:
        got = download_mcws()
        if got:
            return got
        log("  ⚠️ ATTENZIONE: uso l'ultimo listino già scaricato.")
    found = latest(MCWS_DIR, "mcws_inventory_*.csv")
    if not found:
        raise SystemExit("ERRORE: nessun listino MCWS disponibile. Scaricane uno "
                         "(opzione «scarica adesso») o aggiorna il catalogo fornitori.")
    return found


# ─────────────────────────── Etichette di disponibilità ──────────────────────
class Labels:
    """Etichetta di disponibilità di ogni prodotto, dall'ultimo catalogo carmodel
    (stesso sito di MCWS): «Disponibile» verde → normale, azzurra → da saltare."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.by_brand: dict = {}       # (marchio normalizzato, codice) -> (stato, testo)
        self.by_code: dict = {}        # codice -> (stato, testo), solo se il codice è di un marchio
        self.count = {"disponibile": 0, LABEL_NOT_AVAILABLE: 0, "": 0}
        self.has_column = False
        if path is None:
            return
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.has_column = "disponibilita" in (reader.fieldnames or [])
            if not self.has_column:
                return
            seen_brands: dict = {}
            for r in reader:
                code = match_key((r.get("codice_produttore") or "").strip())
                if not code:
                    continue
                label = ((r.get("disponibilita") or "").strip(), (r.get("etichetta") or "").strip())
                self.count[label[0]] = self.count.get(label[0], 0) + 1
                brand = normalize_string(r.get("trademark") or "")
                self.by_brand[(brand, code)] = label
                seen_brands.setdefault(code, set()).add(brand)
                self.by_code[code] = label
            for code, brands in seen_brands.items():
                if len(brands) > 1:             # stesso codice in più marchi: solo per marchio
                    self.by_code.pop(code, None)

    def __call__(self, brand: str, code_key: str):
        return (self.by_brand.get((normalize_string(brand), code_key))
                or self.by_code.get(code_key))


def load_labels() -> Labels:
    found = latest(CARMODEL_DIR, "carmodel_scraped_*.csv")
    if not found:
        log("  ⚠️ Etichette di disponibilità: nessun catalogo carmodel scaricato, non posso "
            "riconoscere i prodotti non disponibili (nessuno viene saltato). "
            "Aggiorna il catalogo fornitori.")
        return Labels()
    labels = Labels(found)
    if not labels.has_column:
        log(f"  ⚠️ Etichette di disponibilità: il catalogo {found.name} è stato scaricato "
            "con una versione vecchia del programma e non le contiene (nessun prodotto "
            "viene saltato). Aggiorna il catalogo fornitori.")
        return labels
    log(f"File etichette usato: {found}")
    log(f"  Etichette di disponibilità: {labels.count.get('disponibile', 0)} «Disponibile» (verde), "
        f"{labels.count.get(LABEL_NOT_AVAILABLE, 0)} non disponibili (azzurra), "
        f"{labels.count.get('', 0)} senza etichetta — {_age(found)}")
    days = (datetime.now() - datetime.fromtimestamp(found.stat().st_mtime)).days
    if days > LABELS_OLD_DAYS:
        log(f"  ⚠️ Le etichette hanno {days} giorni: aggiorna il catalogo fornitori per averle fresche.")
    return labels


# ─────────────────────────── Prodotti da Shopify ─────────────────────────────
VARIANTS_QUERY = """
query($cursor: String, $loc: ID!) {
  productVariants(first: 150, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id sku barcode price compareAtPrice inventoryQuantity
      inventoryItem {
        id tracked unitCost { amount }
        inventoryLevel(locationId: $loc) { quantities(names: ["available"]) { quantity } }
      }
      product { id handle title vendor status tags }
    }
  }
}"""


def fetch_shopify_products(sh: Shopify) -> pd.DataFrame:
    """Tutte le varianti del negozio, con le stesse colonne dell'export Products.csv
    usate dalla logica (+ ID interni per scrivere le modifiche).
    Variant Inventory Qty = disponibili in TUTTE le sedi (quello che vede il cliente);
    _vm_qty = disponibili nella sede Vroomi Models, _other_qty = nelle altre sedi."""
    location = sh.location_id()
    rows, cursor, no_sku, pages = [], None, 0, 0
    while True:
        pages += 1
        page = sh.gql(VARIANTS_QUERY, {"cursor": cursor, "loc": location})["productVariants"]
        for v in page["nodes"]:
            sku = (v.get("sku") or "").strip()
            if not sku:
                no_sku += 1
                continue
            p, item = v["product"], v.get("inventoryItem") or {}
            level = item.get("inventoryLevel")          # None = non presente in Vroomi Models
            vm_qty = sum(q.get("quantity") or 0 for q in (level or {}).get("quantities") or [])
            total = int(v.get("inventoryQuantity") or 0)
            rows.append({
                COL_HANDLE: p["handle"], COL_TITLE: p["title"], COL_VENDOR: p.get("vendor") or "",
                COL_STATUS: p["status"], COL_TAGS: ", ".join(p.get("tags") or []),
                COL_SKU: sku, COL_BARCODE: v.get("barcode") or "",
                COL_QTY: str(total),
                COL_COST: ((item.get("unitCost") or {}).get("amount") or ""),
                COL_PRICE: v.get("price") or "",
                COL_COMPARE: v.get("compareAtPrice") or "",
                "_variant_id": v["id"], "_product_id": p["id"],
                "_item_id": item.get("id", ""), "_tracked": bool(item.get("tracked")),
                "_stocked": level is not None, "_vm_qty": vm_qty, "_other_qty": total - vm_qty,
            })
        if pages % 10 == 0:
            log(f"  … {len(rows)} prodotti letti")
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    if no_sku:
        log(f"  ({no_sku} varianti senza SKU ignorate)")
    return pd.DataFrame(rows)


# ─────────────────────────── Cosa cambia ─────────────────────────────────────
def _tags(s) -> list:
    return [t.strip() for t in str(s or "").split(",") if t.strip()]


def diff_row(old: pd.Series, new: pd.Series) -> dict:
    """Le modifiche da scrivere su Shopify per una variante (vuoto = niente)."""
    ch = {}
    oq, nq = clean_qty(old[COL_QTY]), clean_qty(new[COL_QTY])
    if oq != nq:
        ch["qty"] = (oq, nq)
    for key, col in (("cost", COL_COST), ("price", COL_PRICE), ("compare", COL_COMPARE)):
        o, n = clean_currency(old[col]), clean_currency(new[col])
        if abs(o - n) > 0.005:
            ch[key] = (o, n)
    ot, nt = _tags(old[COL_TAGS]), _tags(new[COL_TAGS])
    add, remove = [t for t in nt if t not in ot], [t for t in ot if t not in nt]
    if add or remove:
        ch["tags"] = (add, remove)
    return ch


def compute(df_shop: pd.DataFrame, prices_only: bool, df_mcws: pd.DataFrame,
            df_bbr: pd.DataFrame, use_bbr: bool,
            qty_only: bool = False, labels=None) -> tuple[pd.DataFrame, list, list, list]:
    """Ritorna (righe nuove, modifiche per riga, log, saltati per l'etichetta).
    Le righe restano nello stesso ordine.
    qty_only: solo la disponibilità (costi, prezzi e tag restano quelli di Shopify).
    labels: etichette di disponibilità (Labels); i prodotti MCWS non «Disponibile» non si toccano."""
    skipped: list = []
    with open(MARKUP_FILE, encoding="utf-8") as f_mk, open(TRADEMARKS_FILE, encoding="utf-8") as f_tm:
        if prices_only:
            new, _stats, logs = process_markup_only(df_shop, f_mk, f_tm)
        else:
            process = process_availability_only if qty_only else process_inventory_v03
            new, stats, _dup, logs = process(
                df_shop, df_mcws, df_bbr, f_mk, f_tm, include_change_log=True,
                only_changes=False, enable_bbr=use_bbr, label_for=labels)
            skipped = stats.get("skipped_unavailable", [])
    untouched = {s["index"] for s in skipped}
    changes = []
    for idx in df_shop.index:
        if idx in untouched:            # etichetta non «Disponibile»: niente, nemmeno lo spostamento
            changes.append({})
            continue
        ch = diff_row(df_shop.loc[idx], new.loc[idx])
        if "qty" in ch and not df_shop.at[idx, "_tracked"]:
            ch.pop("qty")           # magazzino non tracciato su Shopify: la quantità non conta
        if (not prices_only and "qty" not in ch and df_shop.at[idx, "_tracked"]
                and df_shop.at[idx, "_other_qty"] != 0):
            # merce in un'altra sede: va spostata su Vroomi Models (quantità totale uguale)
            ch["move"] = int(df_shop.at[idx, "_other_qty"])
            old = str(new.at[idx, COL_CHANGE_LOG] or "")
            new.at[idx, COL_CHANGE_LOG] = " | ".join(
                x for x in (old, f"LOC: {ch['move']} da altre sedi -> {LOCATION_NAME}") if x)
        changes.append(ch)
    return new, changes, logs, skipped


# ─────────────────────────── Scrittura su Shopify ────────────────────────────
SET_QTY = """
mutation($input: InventorySetQuantitiesInput!) {
  inventorySetQuantities(input: $input) { userErrors { field message } }
}"""
BULK_VARIANTS = """
mutation($pid: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $pid, variants: $variants) { userErrors { field message } }
}"""
TAGS_ADD = """
mutation($id: ID!, $tags: [String!]!) { tagsAdd(id: $id, tags: $tags) { userErrors { message } } }"""
TAGS_REMOVE = """
mutation($id: ID!, $tags: [String!]!) { tagsRemove(id: $id, tags: $tags) { userErrors { message } } }"""


def _errors(res: dict) -> str:
    return "; ".join(e.get("message", str(e)) for e in res.get("userErrors") or [])


def _set_quantities(sh: Shopify, items: list) -> dict:
    """items = [(riga, inventoryItemId, sede, quantità)] → {riga: errore}. A blocchi da 100;
    se un blocco viene rifiutato, riprova uno per uno per capire quale prodotto dà errore."""
    errors = {}

    def send(chunk):
        return _errors(sh.gql(SET_QTY, {"input": {
            "name": "available", "reason": "correction", "ignoreCompareQuantity": True,
            "quantities": [{"inventoryItemId": item, "locationId": location, "quantity": q}
                           for _, item, location, q in chunk]}})["inventorySetQuantities"])

    for i in range(0, len(items), 100):
        chunk = items[i:i + 100]
        try:
            err = send(chunk)
        except Exception as e:
            err = str(e)
        if err and len(chunk) > 1:
            for one in chunk:
                try:
                    e1 = send([one])
                except Exception as e:
                    e1 = str(e)
                if e1:
                    errors[one[0]] = f"quantità: {e1}"
        elif err:
            errors[chunk[0][0]] = f"quantità: {err}"
    return errors


ITEM_LEVELS = """
query($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on InventoryItem {
      id
      inventoryLevels(first: 20) {
        nodes { location { id } quantities(names: ["available"]) { quantity } }
      }
    }
  }
}"""
ACTIVATE = """
mutation($item: ID!, $loc: ID!) {
  inventoryActivate(inventoryItemId: $item, locationId: $loc) {
    inventoryLevel { id }
    userErrors { field message }
  }
}"""


def _other_levels(sh: Shopify, item_ids: list, location: str) -> dict:
    """{inventoryItemId: [sedi diverse da `location` con quantità disponibile ≠ 0]}."""
    out: dict = {}
    for k in range(0, len(item_ids), 50):
        for node in sh.gql(ITEM_LEVELS, {"ids": item_ids[k:k + 50]})["nodes"]:
            if not node:
                continue
            out[node["id"]] = [
                lv["location"]["id"] for lv in node["inventoryLevels"]["nodes"]
                if lv["location"]["id"] != location
                and sum(q.get("quantity") or 0 for q in lv.get("quantities") or []) != 0]
    return out


def _activate(sh: Shopify, item: str, location: str) -> str:
    """Rende il prodotto gestibile nella sede (se non lo era). Ritorna l'errore o ""."""
    try:
        return _errors(sh.gql(ACTIVATE, {"item": item, "loc": location})["inventoryActivate"])
    except Exception as e:
        return str(e)


def _money(x: float) -> str:
    return f"{x:.2f}"


def apply_changes(sh: Shopify, df: pd.DataFrame, changes: list) -> dict:
    """Scrive le modifiche. Ritorna {indice riga: errore} (assente = ok)."""
    errors: dict = {}
    todo = [i for i, ch in enumerate(changes) if ch]

    # 1. Quantità: sempre nella sede Vroomi Models; le altre sedi del prodotto vanno a 0
    moves = [i for i in todo if "qty" in changes[i] or "move" in changes[i]]
    if moves:
        loc = sh.location_id()
        others = _other_levels(sh, [df.iloc[i]["_item_id"] for i in moves
                                    if df.iloc[i]["_other_qty"] != 0], loc)
        items = []
        for i in moves:
            row, ch = df.iloc[i], changes[i]
            target = ch["qty"][1] if "qty" in ch else max(clean_qty(row[COL_QTY]), 0)
            if row["_stocked"] or target != 0:
                if not row["_stocked"]:
                    err = _activate(sh, row["_item_id"], loc)
                    if err:
                        errors[i] = f"quantità: {err}"
                        continue
                items.append((i, row["_item_id"], loc, target))
            items += [(i, row["_item_id"], other, 0) for other in others.get(row["_item_id"], [])]
        n_move = sum(1 for i in moves if "move" in changes[i])
        log(f"  Disponibilità: {len(moves)} prodotti (sede {LOCATION_NAME}"
            + (f", di cui {n_move} spostati da altre sedi" if n_move else "") + ")…")
        for i, err in _set_quantities(sh, items).items():
            errors[i] = (errors.get(i, "") + f" {err}").strip()

    # 2. Prezzo, prezzo barrato e costo: una chiamata per prodotto
    by_product: dict = {}
    for i in todo:
        ch = changes[i]
        v = {}
        if "price" in ch:
            v["price"] = _money(ch["price"][1])
        if "compare" in ch:
            v["compareAtPrice"] = _money(ch["compare"][1]) if ch["compare"][1] > 0 else None
        if "cost" in ch:
            v["inventoryItem"] = {"cost": _money(ch["cost"][1])}
        if v:
            v["id"] = df.iloc[i]["_variant_id"]
            by_product.setdefault(df.iloc[i]["_product_id"], []).append((i, v))
    if by_product:
        log(f"  Prezzi e costi: {sum(len(v) for v in by_product.values())} prodotti…")
    for n, (pid, items) in enumerate(by_product.items(), 1):
        try:
            err = _errors(sh.gql(BULK_VARIANTS, {"pid": pid, "variants": [v for _, v in items]})
                          ["productVariantsBulkUpdate"])
        except Exception as e:
            err = str(e)
        if err:
            for i, _ in items:
                errors[i] = (errors.get(i, "") + f" prezzo: {err}").strip()
        if n % 100 == 0:
            log(f"  … {n}/{len(by_product)}")

    # 3. Tag SALE
    tag_ops: dict = {}
    for i in todo:
        if "tags" in changes[i]:
            add, remove = changes[i]["tags"]
            op = tag_ops.setdefault(df.iloc[i]["_product_id"], {"add": set(), "remove": set(), "rows": []})
            op["add"].update(add)
            op["remove"].update(remove)
            op["rows"].append(i)
    for pid, op in tag_ops.items():
        for mutation, name, tags in ((TAGS_ADD, "tagsAdd", op["add"]), (TAGS_REMOVE, "tagsRemove", op["remove"])):
            if not tags:
                continue
            try:
                err = _errors(sh.gql(mutation, {"id": pid, "tags": sorted(tags)})[name])
            except Exception as e:
                err = str(e)
            if err:
                for i in op["rows"]:
                    errors[i] = (errors.get(i, "") + f" tag: {err}").strip()
    return errors


# ─────────────────────────── Report ──────────────────────────────────────────
def write_report(new: pd.DataFrame, changes: list, results: dict | None, sh: Shopify) -> Path:
    rows = [i for i, ch in enumerate(changes) if ch]
    out = new.iloc[rows].copy()
    out[COL_RESULT] = ["" if results is None else
                       (f"❌ {results[i]}" if i in results else "✅ aggiornato") for i in rows]
    out[COL_URL] = [sh.admin_url(pid) for pid in out["_product_id"]]
    for c in REPORT_COLUMNS:
        if c not in out.columns:
            out[c] = ""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"inventario_{datetime.now():%Y-%m-%d_%H%M%S}.csv"
    out[REPORT_COLUMNS].to_csv(path, index=False)
    for old in sorted(REPORT_DIR.glob("inventario_*.csv"), key=lambda p: p.stat().st_mtime)[:-KEEP_REPORTS]:
        old.unlink(missing_ok=True)
    return path


# ─────────────────────────── Main ────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="scrive davvero su Shopify")
    ap.add_argument("--solo-prezzi", action="store_true", help="ricalcola solo i prezzi (niente listini)")
    ap.add_argument("--solo-disponibilita", action="store_true",
                    help="aggiorna solo la disponibilità (costi, prezzi e tag non si toccano)")
    ap.add_argument("--mcws", help="listino MCWS da usare (default: l'ultimo scaricato)")
    ap.add_argument("--mcws-nuovo", action="store_true", help="scarica adesso un listino MCWS nuovo")
    ap.add_argument("--bbr", help="giacenze BBR da usare (default: l'ultimo file caricato)")
    ap.add_argument("--senza-bbr", action="store_true", help="non considerare le giacenze BBR")
    ap.add_argument("--forza", action="store_true", help="applica anche se troppi prodotti diventano esauriti")
    args = ap.parse_args()
    if args.solo_prezzi and args.solo_disponibilita:
        ap.error("--solo-prezzi e --solo-disponibilita non vanno insieme")
    what = ("solo prezzi" if args.solo_prezzi else
            "solo disponibilità" if args.solo_disponibilita else "disponibilità, costi e prezzi")

    _load_env(REPO / "credenziali.env")
    _load_env(Path.home() / ".env.vroomi")

    log("════════════════════════════════════════════════════════")
    log(f"VROOMI — AGGIORNA L'INVENTARIO {'[APPLICA SU SHOPIFY]' if args.apply else '[CONTROLLO]'}")
    log(f"Avvio: {datetime.now():%d/%m/%Y %H:%M:%S}  |  "
        f"{what}")
    log("════════════════════════════════════════════════════════")

    df_mcws = df_bbr = pd.DataFrame()
    use_bbr = False
    labels = None
    if not args.solo_prezzi:
        log("▶ [1/4] Listini dei fornitori")
        mcws = resolve_mcws(args.mcws, args.mcws_nuovo)
        df_mcws = read_table(mcws)
        log(f"File MCWS usato: {mcws}")
        log(f"  Listino MCWS: {len(df_mcws)} righe, {_age(mcws)}")
        if len(df_mcws) < MIN_MCWS_ROWS:
            raise SystemExit(f"ERRORE: il listino MCWS ha solo {len(df_mcws)} righe: "
                             "sembra incompleto, mi fermo.")
        use_bbr = not args.senza_bbr
        if use_bbr:
            bbr = Path(args.bbr) if args.bbr else latest(BBR_DIR, "bbr_giacenze_*")
            if not bbr or not bbr.exists():
                raise SystemExit("ERRORE: manca il file delle giacenze BBR. Caricalo nel "
                                 "pannello oppure spegni «Considera anche BBR».")
            df_bbr = read_table(bbr)
            log(f"File BBR usato: {bbr}")
            log(f"  Giacenze BBR: {len(df_bbr)} righe, {_age(bbr)}")
        else:
            log("  Giacenze BBR: non considerate")
        labels = load_labels()

    log("▶ [2/4] Leggo i prodotti dal negozio Shopify")
    sh = Shopify.from_env()
    df_shop = fetch_shopify_products(sh)
    log(f"Prodotti letti da Shopify: {len(df_shop)}")
    if df_shop.empty:
        raise SystemExit("ERRORE: Shopify non ha restituito nessun prodotto.")

    log("▶ [3/4] Confronto con i listini e i ricarichi")
    new, changes, logic_log, skipped = compute(df_shop, args.solo_prezzi, df_mcws, df_bbr, use_bbr,
                                               qty_only=args.solo_disponibilita, labels=labels)
    for m in logic_log:
        if not str(m).startswith("[CHECK"):
            log(f"  {m}")
    n = lambda key, cond=lambda v: True: sum(1 for c in changes if key in c and cond(c[key]))  # noqa: E731
    back, out_of_stock = n("qty", lambda v: v[0] == 0 < v[1]), n("qty", lambda v: v[0] > 0 == v[1])
    total = sum(1 for c in changes if c)
    available = int(sum(1 for i in df_shop.index
                        if df_shop.at[i, "_tracked"] and clean_qty(df_shop.at[i, COL_QTY]) > 0))
    log(f"Prodotti da aggiornare: {total}")
    log(f"  tornano disponibili: {back}")
    log(f"  diventano esauriti: {out_of_stock}")
    log(f"  prezzi cambiati: {n('price')}")
    log(f"  costi cambiati: {n('cost')}")
    log(f"  spostati su {LOCATION_NAME}: {n('move')}")
    log(f"  disponibili ora nel negozio: {available}")
    if not args.solo_prezzi:
        log(f"Saltati perché NON DISPONIBILI (etichetta azzurra, non «Disponibile»): {len(skipped)}")
        for sk in skipped:
            log(f"  - SKU {sk['sku']}  [{sk['brand']}]  etichetta «{sk['label'] or '?'}» (azzurra)"
                f"  — {sk['title']}  → non toccato")

    too_many = out_of_stock > max(MIN_OUT_OF_STOCK_BLOCK, available * MAX_OUT_OF_STOCK_PCT / 100)
    if too_many:
        log(f"TROPPI ESAURITI: {out_of_stock} prodotti su {available} disponibili diventerebbero "
            "esauriti. Il listino potrebbe essere incompleto: controlla prima di applicare.")

    results = None
    if not args.apply:
        log("▶ [4/4] Controllo finito: su Shopify non ho cambiato niente.")
    elif total == 0:
        log("▶ [4/4] Niente da aggiornare: il negozio è già allineato.")
    elif too_many and not args.forza:
        log("▶ [4/4] BLOCCATO: non ho applicato niente (troppi esauriti). Se è tutto giusto, "
            "rilancia scegliendo «applica lo stesso».")
    else:
        log(f"▶ [4/4] Scrivo le modifiche su Shopify ({total} prodotti)")
        results = apply_changes(sh, df_shop, changes)
        for i, err in list(results.items())[:20]:
            log(f"  ERRORE {df_shop.iloc[i][COL_SKU]}: {err}")
        log(f"Aggiornati su Shopify: {total - len(results)}")
        log(f"Errori su Shopify: {len(results)}")

    report = write_report(new, changes, results, sh)
    log(f"Report: {report}")
    log("FINE")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # errore leggibile nel log del pannello
        print(f"ERRORE: {e}", flush=True)
        sys.exit(1)
