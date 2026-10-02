"""
inventario_sync.py — "Aggiorna l'inventario" in automatico, senza caricare file.

  1. legge i prodotti DIRETTAMENTE da Shopify (Admin API, stesse credenziali
     dello strumento newsletter) al posto dell'export Products.csv
  2. listino MCWS: l'ultimo scaricato dal catalogo automatico (dati/mcws/),
     oppure ne scarica uno nuovo adesso (--mcws-nuovo, si apre Chrome)
  3. giacenze BBR: l'ultimo file caricato nel pannello (dati/bbr/), facoltativo
  4. calcola le modifiche con la stessa logica di sempre (logic_v03.py)
  5. con --apply le scrive su Shopify: quantità, costo, prezzo, prezzo barrato, tag SALE

Senza --apply non scrive niente su Shopify (è il "Controlla").
Protezione: se troppi prodotti diventerebbero esauriti (listino sbagliato o
incompleto) --apply si ferma, a meno di --forza.

Uso (dalla cartella principale):
  .venv/bin/python -m pannello.inventario_sync                 # controllo
  .venv/bin/python -m pannello.inventario_sync --apply         # applica
  opzioni: --solo-prezzi  --mcws-nuovo  --mcws FILE  --bbr FILE  --senza-bbr  --forza
"""

from __future__ import annotations

import argparse
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
    clean_currency, clean_qty, process_inventory_v03, process_markup_only,
)
from shopify import Shopify, _load_env  # noqa: E402

DATA_DIR = REPO / "dati"
MCWS_DIR = DATA_DIR / "mcws"
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


# ─────────────────────────── Prodotti da Shopify ─────────────────────────────
VARIANTS_QUERY = """
query($cursor: String) {
  productVariants(first: 200, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id sku barcode price compareAtPrice inventoryQuantity
      inventoryItem { id tracked unitCost { amount } }
      product { id handle title vendor status tags }
    }
  }
}"""


def fetch_shopify_products(sh: Shopify) -> pd.DataFrame:
    """Tutte le varianti del negozio, con le stesse colonne dell'export Products.csv
    usate dalla logica (+ ID interni per scrivere le modifiche)."""
    rows, cursor, no_sku, pages = [], None, 0, 0
    while True:
        pages += 1
        page = sh.gql(VARIANTS_QUERY, {"cursor": cursor})["productVariants"]
        for v in page["nodes"]:
            sku = (v.get("sku") or "").strip()
            if not sku:
                no_sku += 1
                continue
            p, item = v["product"], v.get("inventoryItem") or {}
            rows.append({
                COL_HANDLE: p["handle"], COL_TITLE: p["title"], COL_VENDOR: p.get("vendor") or "",
                COL_STATUS: p["status"], COL_TAGS: ", ".join(p.get("tags") or []),
                COL_SKU: sku, COL_BARCODE: v.get("barcode") or "",
                COL_QTY: str(v.get("inventoryQuantity") or 0),
                COL_COST: ((item.get("unitCost") or {}).get("amount") or ""),
                COL_PRICE: v.get("price") or "",
                COL_COMPARE: v.get("compareAtPrice") or "",
                "_variant_id": v["id"], "_product_id": p["id"],
                "_item_id": item.get("id", ""), "_tracked": bool(item.get("tracked")),
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
            df_bbr: pd.DataFrame, use_bbr: bool) -> tuple[pd.DataFrame, list, list]:
    """Ritorna (righe nuove, modifiche per riga, log). Le righe restano nello stesso ordine."""
    with open(MARKUP_FILE, encoding="utf-8") as f_mk, open(TRADEMARKS_FILE, encoding="utf-8") as f_tm:
        if prices_only:
            new, _stats, logs = process_markup_only(df_shop, f_mk, f_tm)
        else:
            new, _stats, _dup, logs = process_inventory_v03(
                df_shop, df_mcws, df_bbr, f_mk, f_tm, include_change_log=True,
                only_changes=False, enable_bbr=use_bbr)
    changes = []
    for idx in df_shop.index:
        ch = diff_row(df_shop.loc[idx], new.loc[idx])
        if "qty" in ch and not df_shop.at[idx, "_tracked"]:
            ch.pop("qty")           # magazzino non tracciato su Shopify: la quantità non conta
        changes.append(ch)
    return new, changes, logs


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


def _set_quantities(sh: Shopify, location: str, items: list) -> dict:
    """items = [(riga, inventoryItemId, quantità)] → {riga: errore}. A blocchi da 100;
    se un blocco viene rifiutato, riprova uno per uno per capire quale prodotto dà errore."""
    errors = {}

    def send(chunk):
        return _errors(sh.gql(SET_QTY, {"input": {
            "name": "available", "reason": "correction", "ignoreCompareQuantity": True,
            "quantities": [{"inventoryItemId": item, "locationId": location, "quantity": q}
                           for _, item, q in chunk]}})["inventorySetQuantities"])

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


def _money(x: float) -> str:
    return f"{x:.2f}"


def apply_changes(sh: Shopify, df: pd.DataFrame, changes: list) -> dict:
    """Scrive le modifiche. Ritorna {indice riga: errore} (assente = ok)."""
    errors: dict = {}
    todo = [i for i, ch in enumerate(changes) if ch]

    # 1. Quantità (sede di magazzino del negozio, come per le schede delle newsletter)
    qty = [(i, df.iloc[i]["_item_id"], changes[i]["qty"][1]) for i in todo if "qty" in changes[i]]
    if qty:
        locations = [n for n in sh.gql("{ locations(first: 10) { nodes { id isActive } } }")
                     ["locations"]["nodes"] if n.get("isActive")]
        if len(locations) > 1:
            log(f"  ⚠️ Il negozio ha {len(locations)} sedi di magazzino: aggiorno solo la "
                "principale (SHOPIFY_LOCATION_ID in credenziali.env per sceglierne un'altra).")
        log(f"  Disponibilità: {len(qty)} prodotti…")
        errors.update(_set_quantities(sh, sh.location_id(), qty))

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
    ap.add_argument("--mcws", help="listino MCWS da usare (default: l'ultimo scaricato)")
    ap.add_argument("--mcws-nuovo", action="store_true", help="scarica adesso un listino MCWS nuovo")
    ap.add_argument("--bbr", help="giacenze BBR da usare (default: l'ultimo file caricato)")
    ap.add_argument("--senza-bbr", action="store_true", help="non considerare le giacenze BBR")
    ap.add_argument("--forza", action="store_true", help="applica anche se troppi prodotti diventano esauriti")
    args = ap.parse_args()

    _load_env(REPO / "credenziali.env")
    _load_env(Path.home() / ".env.vroomi")

    log("════════════════════════════════════════════════════════")
    log(f"VROOMI — AGGIORNA L'INVENTARIO {'[APPLICA SU SHOPIFY]' if args.apply else '[CONTROLLO]'}")
    log(f"Avvio: {datetime.now():%d/%m/%Y %H:%M:%S}  |  "
        f"{'solo prezzi' if args.solo_prezzi else 'disponibilità, costi e prezzi'}")
    log("════════════════════════════════════════════════════════")

    df_mcws = df_bbr = pd.DataFrame()
    use_bbr = False
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

    log("▶ [2/4] Leggo i prodotti dal negozio Shopify")
    sh = Shopify.from_env()
    df_shop = fetch_shopify_products(sh)
    log(f"Prodotti letti da Shopify: {len(df_shop)}")
    if df_shop.empty:
        raise SystemExit("ERRORE: Shopify non ha restituito nessun prodotto.")

    log("▶ [3/4] Confronto con i listini e i ricarichi")
    new, changes, logic_log = compute(df_shop, args.solo_prezzi, df_mcws, df_bbr, use_bbr)
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
    log(f"  disponibili ora nel negozio: {available}")

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
