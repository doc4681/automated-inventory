"""
inventario_ui.py — pagina "Aggiorna l'inventario".
Carichi l'export prodotti di Shopify (+ listino MCWS e, se vuoi, giacenze BBR) e
scarichi il file con disponibilità/costi/prezzi aggiornati da importare su Shopify.
La logica di calcolo è invariata: pannello/logic.py e pannello/logic_v03.py.
"""

from __future__ import annotations

import os
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from pannello import controller as ctl
from pannello.logic import process_inventory, OUTPUT_PREFIX as OUTPUT_PREFIX_LEGACY, COL_SHOPIFY_SKU
from pannello.logic_v03 import (
    process_inventory_v03, process_markup_only, OUTPUT_PREFIX as OUTPUT_PREFIX_V03, COL_MCWS_CODE,
)
from pannello.ui_common import IS_MAC, go, num, page_header, step, when

TRADEMARKS_FILE = ctl.TRADEMARKS_FILE
MARKUP_FILE = ctl.MARKUP_FILE

# Colonne che DEVONO restare testo (codici con zeri iniziali: es. "03518").
# Excel al doppio click converte il CSV in numero e perde lo zero → mismatch
# al giro successivo. L'export .xlsx forza queste colonne come Testo.
TEXT_FORCED_COLUMNS = [COL_SHOPIFY_SKU, COL_MCWS_CODE, "Our Code"]

FULL, PRICES, LEGACY = "full", "prices", "legacy"
MODES = {
    FULL: ("Disponibilità, costi e prezzi  (consigliato)",
           "Segna come esauriti i prodotti che i fornitori non hanno più, rimette disponibili "
           "quelli tornati in magazzino e aggiorna costi e prezzi di vendita."),
    PRICES: ("Solo i prezzi",
             "Ricalcola i prezzi di vendita con i ricarichi attuali, senza toccare la "
             "disponibilità. Serve solo l'export di Shopify."),
    LEGACY: ("Solo la disponibilità  (vecchio export a 6 colonne)",
             "Per chi usa ancora l'export ridotto Shopify_Products.csv: aggiorna solo "
             "disponibile / esaurito."),
}


# ─────────────────────────── Lettura / scrittura file ────────────────────────
def dataframe_to_excel_bytes(df: pd.DataFrame, text_columns: list) -> bytes:
    """Genera un .xlsx con le colonne in text_columns formattate come Testo
    (number_format='@'), così Excel non le converte mai in numero."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
        worksheet = writer.sheets["Sheet1"]
        for col_name in text_columns:
            if col_name not in df.columns:
                continue
            col_idx = df.columns.get_loc(col_name) + 1  # openpyxl è 1-based
            for row_idx in range(2, len(df) + 2):       # riga 1 = header
                cell = worksheet.cell(row=row_idx, column=col_idx)
                if cell.value is not None:
                    cell.value = str(cell.value)
                cell.number_format = "@"
    return output.getvalue()


def load_dataframe(src):
    """src = file caricato dall'utente oppure Path (listino scaricato in automatico)."""
    filename = src.name.lower()
    _, ext = os.path.splitext(filename)
    try:
        if ext == '.csv':
            try:
                return pd.read_csv(src, dtype=str)
            except Exception:
                if hasattr(src, "seek"):
                    src.seek(0)
                return pd.read_csv(src, dtype=str, sep=';')
        elif ext in ['.xls', '.xlsx']:
            return pd.read_excel(src, dtype=str)
        else:
            raise ValueError(f"Formato file non supportato: {ext}")
    except Exception as e:
        raise ValueError(f"Errore nella lettura del file {filename}: {str(e)}")


def _valid_trademarks() -> list:
    try:
        return [t for t in TRADEMARKS_FILE.read_text(encoding="utf-8").splitlines() if t.strip()]
    except OSError:
        return []


# ─────────────────────────── Elaborazione ────────────────────────────────────
def _process(mode, file_shop, src_mcws, file_bbr, use_bbr, only_changes, include_log) -> dict:
    df_shop = load_dataframe(file_shop)
    duplicates = []
    with open(TRADEMARKS_FILE, encoding="utf-8") as f_tm:
        if mode == LEGACY:
            df_mcws = load_dataframe(src_mcws)
            df_bbr = load_dataframe(file_bbr) if (use_bbr and file_bbr) else pd.DataFrame()
            df, stats, duplicates, log = process_inventory(df_shop, df_mcws, df_bbr, f_tm,
                                                           enable_bbr=use_bbr)
            prefix = OUTPUT_PREFIX_LEGACY
        elif mode == FULL:
            df_mcws = load_dataframe(src_mcws)
            df_bbr = load_dataframe(file_bbr) if (use_bbr and file_bbr) else pd.DataFrame()
            with open(MARKUP_FILE, encoding="utf-8") as f_mk:
                df, stats, duplicates, log = process_inventory_v03(
                    df_shop, df_mcws, df_bbr, f_mk, f_tm, include_change_log=include_log,
                    only_changes=only_changes, enable_bbr=use_bbr)
            prefix = OUTPUT_PREFIX_V03
        else:
            with open(MARKUP_FILE, encoding="utf-8") as f_mk:
                df, stats, log = process_markup_only(df_shop, f_mk, f_tm)
            prefix = "MARKUP_UPDATE"
    return {"mode": mode, "df": df, "stats": stats, "log": log, "duplicates": duplicates,
            "prefix": prefix, "ts": datetime.now().strftime("%Y%m%d_%H%M%S")}


def _show_result(r: dict) -> None:
    df, stats, mode = r["df"], r["stats"], r["mode"]
    step(4, "Scarica il file e importalo su Shopify")

    if df is None or len(df) == 0:
        st.info("✅ Fatto: **non c'è niente da aggiornare**. Il negozio è già allineato ai listini.")
        _details(r)
        return

    if mode == PRICES:
        cols = st.columns(3)
        cols[0].metric("Prodotti controllati", num(stats["processed"]))
        cols[1].metric("Prezzi cambiati", num(stats["updated_price"]))
        cols[2].metric("Saltati", num(stats["skipped"]),
                       help="Prodotti senza costo o di marchi senza ricarico.")
    else:
        inv = stats if mode == LEGACY else stats["inventory"]
        cols = st.columns(4 if mode == FULL else 3)
        cols[0].metric("Prodotti controllati", num(inv["total"]))
        cols[1].metric("Tornano disponibili", num(inv["updates_1"]))
        cols[2].metric("Diventano esauriti", num(inv["updates_0"]))
        if mode == FULL:
            cols[3].metric("Prezzi cambiati", num(stats.get("updated_price", 0)),
                           help=f"Costi cambiati: {num(stats.get('updated_cost', 0))}")

    st.success(f"Il file è pronto: **{num(len(df))} righe** da importare su Shopify.")
    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "⬇️ Scarica il file Excel  (consigliato)",
            dataframe_to_excel_bytes(df, TEXT_FORCED_COLUMNS),
            f"{r['prefix']}_{r['ts']}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary", use_container_width=True)
    with d2:
        st.download_button("⬇️ Scarica in formato CSV", df.to_csv(index=False).encode("utf-8"),
                           f"{r['prefix']}_{r['ts']}.csv", "text/csv", use_container_width=True)
    st.caption("Il file Excel mantiene gli zeri iniziali dei codici (es. 03518); "
               "il CSV aperto con Excel li perde.")
    _details(r)


def _details(r: dict) -> None:
    if r["duplicates"]:
        st.warning("⚠️ Nel listino del fornitore alcuni codici compaiono più volte. "
                   "Controlla questi prodotti:")
        st.dataframe(pd.DataFrame(r["duplicates"]), use_container_width=True)
    if r["df"] is not None and len(r["df"]):
        with st.expander("👀 Guarda le prime righe del file"):
            st.dataframe(r["df"].head(20), use_container_width=True)
    with st.expander("🔎 Dettaglio di cosa è stato fatto"):
        st.text("\n".join(str(m) for m in r["log"]) or "—")


# ─────────────────────────── Pagina ──────────────────────────────────────────
def _fid(f):
    """Identità di un file caricato (o del listino automatico) per capire se è cambiato."""
    return None if f is None else str(getattr(f, "file_id", f))


def _mcws_source(mode):
    """Listino MCWS: quello scaricato in automatico (se c'è) oppure caricato a mano."""
    auto = ctl.latest_mcws_stocklist() if IS_MAC else None
    st.markdown("**Listino MCWS**")
    if auto:
        age = (datetime.now() - auto["mtime"]).days
        use_auto = st.radio(
            "Listino MCWS", label_visibility="collapsed", key=f"mcws_src_{mode}",
            options=["auto", "upload"],
            format_func=lambda o: (f"Usa quello scaricato in automatico ({when(auto['mtime'])})"
                                   if o == "auto" else "Carico io un file (MCWS_stocklist.csv)"),
        ) == "auto"
        if use_auto:
            if age >= 3:
                st.warning(f"Questo listino ha {age} giorni. Per averne uno nuovo apri "
                           "**Catalogo fornitori** e premi *Aggiorna adesso*, oppure carica "
                           "tu un file scaricato da modelcarswholesale.com.")
            return auto["path"]
    return st.file_uploader("Listino MCWS (MCWS_stocklist.csv, scaricato da modelcarswholesale.com)",
                            type=["csv"], key=f"up_mcws_{mode}",
                            label_visibility="collapsed" if auto else "visible")


def render_inventario():
    page_header("📦 Aggiorna l'inventario",
                "Prepara il file con disponibilità, costi e prezzi aggiornati, "
                "da importare su Shopify.")

    # ── 1. Cosa aggiornare ───────────────────────────────────────────────────
    step(1, "Cosa vuoi aggiornare?")
    mode = st.radio("Cosa vuoi aggiornare?", list(MODES), label_visibility="collapsed",
                    format_func=lambda m: MODES[m][0],
                    captions=[MODES[m][1] for m in MODES], key="inv_mode")
    # ── 2. File ──────────────────────────────────────────────────────────────
    step(2, "Carica i file")
    src_mcws = file_bbr = None
    use_bbr = False
    with st.container(border=True):
        st.markdown("**Prodotti del negozio** — export da Shopify")
        file_shop = st.file_uploader(
            "Shopify_Products.csv (6 colonne)" if mode == LEGACY else "Products.csv (12 colonne)",
            type=["csv"], key=f"up_shop_{mode}")

        if mode != PRICES:
            st.divider()
            src_mcws = _mcws_source(mode)
            st.divider()
            use_bbr = st.toggle("Considera anche il magazzino **BBR Models**", value=True,
                                key=f"bbr_on_{mode}",
                                help="Se è acceso, i prodotti BBR vengono controllati sulle "
                                     "giacenze BBR (e nel caso consigliato anche sui loro costi).")
            if use_bbr:
                file_bbr = st.file_uploader("Giacenze BBR (export CSV o Excel)",
                                            type=["csv", "xls", "xlsx"], key=f"up_bbr_{mode}")

    only_changes, include_log = True, True
    if mode == FULL:
        with st.expander("⚙️ Opzioni del file finale"):
            only_changes = st.radio(
                "Cosa mettere nel file", ["changed", "all"],
                format_func=lambda o: ("Solo i prodotti che cambiano  (consigliato)" if o == "changed"
                                       else "Tutti i prodotti"), key="inv_scope") == "changed"
            include_log = st.checkbox("Aggiungi una colonna «Change Log» che spiega cosa cambia "
                                      "in ogni riga", value=True, key="inv_log")

    tms = _valid_trademarks()
    with st.expander(f"🏷️ Marchi considerati ({len(tms)})"):
        if tms:
            st.write(", ".join(tms))
        else:
            st.warning("Il file config/Valid_Trademarks.txt manca o è vuoto.")
        if IS_MAC:
            st.button("Modifica i marchi o i ricarichi", on_click=go, args=("impostazioni",),
                      key="inv_to_settings")

    # ── 3. Avvio ─────────────────────────────────────────────────────────────
    step(3, "Prepara il file")
    missing = [] if file_shop else ["prodotti del negozio"]
    if mode != PRICES and not src_mcws:
        missing.append("listino MCWS")
    if use_bbr and not file_bbr:
        missing.append("giacenze BBR")
    if missing:
        st.caption("Per continuare carica: **" + "**, **".join(missing) + "**.")

    # Se cambiano scelte o file, il risultato precedente non vale più.
    signature = (mode, _fid(file_shop), _fid(src_mcws), _fid(file_bbr), use_bbr,
                 only_changes, include_log)
    if st.session_state.get("inv_result", {}).get("signature") != signature:
        st.session_state.pop("inv_result", None)

    if st.button("▶  Prepara il file di aggiornamento", type="primary", disabled=bool(missing),
                 key="inv_go"):
        with st.spinner("Sto confrontando i prodotti con i listini…"):
            try:
                st.session_state["inv_result"] = _process(
                    mode, file_shop, src_mcws, file_bbr, use_bbr, only_changes, include_log)
                st.session_state["inv_result"]["signature"] = signature
            except Exception as e:
                st.session_state.pop("inv_result", None)
                st.error(f"Non sono riuscito a preparare il file. Controlla di aver caricato i "
                         f"file giusti.\n\n**Dettaglio:** {e}")

    # Il risultato resta in memoria: cliccare "Scarica" non lo fa sparire.
    if "inv_result" in st.session_state:
        _show_result(st.session_state["inv_result"])
