"""
sync_ui.py — Tab "Sync inventario (quantità/costi)".
È la webapp Streamlit ORIGINALE (upload CSV → elabora → download), invariata,
incapsulata in render_sync_tab() per stare dentro un tab del pannello.
"""

import os
from datetime import datetime

import pandas as pd
import streamlit as st

from logic import (
    process_inventory, OUTPUT_PREFIX as OUTPUT_PREFIX_LEGACY,
    COL_SHOPIFY_SKU, COL_SHOPIFY_QTY,
)
from logic_v03 import (
    process_inventory_v03, process_markup_only, OUTPUT_PREFIX as OUTPUT_PREFIX_V03,
)


def load_dataframe(uploaded_file):
    filename = uploaded_file.name.lower()
    _, ext = os.path.splitext(filename)
    try:
        if ext == '.csv':
            try:
                return pd.read_csv(uploaded_file, dtype=str)
            except Exception:
                uploaded_file.seek(0)
                return pd.read_csv(uploaded_file, dtype=str, sep=';')
        elif ext in ['.xls', '.xlsx']:
            return pd.read_excel(uploaded_file, dtype=str)
        else:
            raise ValueError(f"Formato file non supportato: {ext}")
    except Exception as e:
        raise ValueError(f"Errore nella lettura del file {filename}: {str(e)}")


def render_sync_tab():
    st.markdown("### 🔄 Sync inventario (quantità / costi / prezzi)")
    st.caption("Carica i listini inventario per generare il file di aggiornamento per Shopify.")

    if 'process_mode' not in st.session_state:
        st.session_state['process_mode'] = "Formato Originale (3 file)"

    MODE_ORIGINAL = "Formato Originale (3 file)"
    MODE_V03 = "Formato V03 (1 file Products.csv)"
    MODE_MARKUP = "Adeguamento Markup (Solo Prezzi)"

    current_index = 0
    if st.session_state['process_mode'] == MODE_V03:
        current_index = 1
    elif st.session_state['process_mode'] == MODE_MARKUP:
        current_index = 2

    process_mode = st.radio("Scegli il formato di elaborazione:",
                            [MODE_ORIGINAL, MODE_V03, MODE_MARKUP],
                            index=current_index, horizontal=False)

    if process_mode != st.session_state['process_mode']:
        st.session_state['process_mode'] = process_mode
        for key in ['file_shopify', 'file_mcws', 'file_bbr', 'file_products']:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

    st.markdown("---")
    col_upload, col_info = st.columns([1, 1])
    files_loaded = False
    OUTPUT_PREFIX = "UPDATE"
    use_bbr_file = True
    file_shopify = file_mcws = file_bbr = None

    with col_upload:
        st.markdown("**1. Carica i File**")
        if process_mode == MODE_ORIGINAL:
            st.info("📄 **Formato Originale**: Carica i file separati")
            use_bbr_file = st.checkbox("Abilita controllo specifico BBR (Richiede file Export)",
                                       value=True, key="bbr_orig")
            file_shopify = st.file_uploader("📁 **Shopify_Products.csv** (6 colonne)",
                                            type=["csv"], key="file_shopify")
            file_mcws = st.file_uploader("📁 **MCWS_stocklist.csv**", type=["csv"], key="file_mcws")
            if use_bbr_file:
                file_bbr = st.file_uploader("📁 **BBR_export**", type=["csv", "xls", "xlsx"], key="file_bbr")
                if file_shopify and file_mcws and file_bbr:
                    files_loaded = True
            else:
                file_bbr = None
                if file_shopify and file_mcws:
                    files_loaded = True
            OUTPUT_PREFIX = OUTPUT_PREFIX_LEGACY

        elif process_mode == MODE_V03:
            st.info("📦 **Formato V03**: Products.csv ha 12 colonne")
            use_bbr_file = st.checkbox("Abilita controllo specifico BBR (Richiede file Export)",
                                       value=True, key="bbr_v03")
            file_shopify = st.file_uploader("📁 **Products.csv** (12 colonne)",
                                            type=["csv"], key="file_shopify")
            file_mcws = st.file_uploader("📁 **MCWS_stocklist.csv**", type=["csv"], key="file_mcws")
            if use_bbr_file:
                file_bbr = st.file_uploader("📁 **BBR_export**", type=["csv", "xls", "xlsx"], key="file_bbr")
                if file_shopify and file_mcws and file_bbr:
                    files_loaded = True
            else:
                file_bbr = None
                if file_shopify and file_mcws:
                    files_loaded = True
            OUTPUT_PREFIX = OUTPUT_PREFIX_V03

        elif process_mode == MODE_MARKUP:
            st.info("🏷️ **Adeguamento Markup**: Carica solo Products.csv")
            file_shopify = st.file_uploader("📁 **Products.csv** (12 colonne)",
                                            type=["csv"], key="file_shopify")
            if file_shopify:
                files_loaded = True
            OUTPUT_PREFIX = "MARKUP_UPDATE"

    with col_info:
        st.markdown("**2. Configurazione**")
        only_changes_param = True
        if process_mode == MODE_V03:
            output_scope = st.radio("📂 **Seleziona Output:**",
                                    ["Solo Righe Modificate (Consigliato)", "File Intero Elaborato"], index=0)
            only_changes_param = (output_scope == "Solo Righe Modificate (Consigliato)")
            st.write("---")
        include_log = True
        if process_mode != MODE_ORIGINAL:
            include_log = st.checkbox("📝 **Includi colonna 'Change Log' nel file output**", value=True)
        st.write("---")
        try:
            with open('Valid_Trademarks.txt', 'r', encoding='utf-8') as f:
                valid_tms = [t for t in f.read().splitlines() if t.strip()]
        except Exception:
            valid_tms = []
        with st.expander(f"ℹ️ Trademark Validi (Caricati da file: {len(valid_tms)})"):
            if valid_tms:
                st.write(", ".join(valid_tms))
            else:
                st.warning("File Valid_Trademarks.txt non trovato o vuoto!")

    st.markdown("---")

    if not files_loaded:
        st.info("👆 Carica i file necessari per abilitare il pulsante di avvio.")
        return

    st.markdown("**3. Elaborazione**")
    if not st.button("🚀 Avvia Elaborazione", type="primary"):
        return

    with st.spinner('Elaborazione in corso...'):
        try:
            df_shopify_loaded = load_dataframe(file_shopify)
            f_trademarks = open('Valid_Trademarks.txt', 'r', encoding='utf-8')
            show_legacy_stats = True
            duplicate_report = []

            if process_mode == MODE_ORIGINAL:
                df_mcws_loaded = load_dataframe(file_mcws)
                df_bbr_loaded = load_dataframe(file_bbr) if (use_bbr_file and file_bbr) else pd.DataFrame()
                result_df, stats, duplicate_report, log_messages = process_inventory(
                    df_shopify_loaded, df_mcws_loaded, df_bbr_loaded, f_trademarks,
                    enable_bbr=use_bbr_file)
            elif process_mode == MODE_V03:
                df_mcws_loaded = load_dataframe(file_mcws)
                df_bbr_loaded = load_dataframe(file_bbr) if (use_bbr_file and file_bbr) else pd.DataFrame()
                with open('Vroomi_Markup.txt', 'r', encoding='utf-8') as f_markup:
                    result_df, stats, duplicate_report, log_messages = process_inventory_v03(
                        df_shopify_loaded, df_mcws_loaded, df_bbr_loaded, f_markup, f_trademarks,
                        include_change_log=include_log, only_changes=only_changes_param,
                        enable_bbr=use_bbr_file)
            else:  # MODE_MARKUP
                with open('Vroomi_Markup.txt', 'r', encoding='utf-8') as f_markup:
                    result_df, stats, log_messages = process_markup_only(
                        df_shopify_loaded, f_markup, f_trademarks)
                show_legacy_stats = False
            f_trademarks.close()

            st.markdown("---")
            st.markdown("**4. Risultati**")
            if result_df is not None and len(result_df) > 0:
                if show_legacy_stats:
                    if process_mode == MODE_ORIGINAL:
                        tot, u1, u0 = stats['total'], stats['updates_1'], stats['updates_0']
                    else:
                        tot, u1, u0 = stats['inventory']['total'], stats['inventory']['updates_1'], stats['inventory']['updates_0']
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Totale SKU", tot)
                    m2.metric("Attivati", u1)
                    m3.metric("Disattivati", u0)
                    m4.metric("Modifiche Tot", u1 + u0)
                    if process_mode == MODE_V03:
                        c1, c2 = st.columns(2)
                        c1.metric("Variazioni Costo", stats.get('cost_changes', 0))
                        c2.metric("Variazioni Prezzo", stats.get('updated_price', 0))
                else:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Righe Processate", stats['processed'])
                    m2.metric("Prezzi Aggiornati", stats['updated_price'])
                    m3.metric("Saltati", stats['skipped'])

                with st.expander("📋 Log Elaborazione"):
                    for msg in log_messages:
                        st.text(msg)
                if duplicate_report:
                    st.warning("⚠️ Trovati duplicati nel listino fornitore.")
                    st.dataframe(pd.DataFrame(duplicate_report))

                st.markdown("### 📥 Download")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"{OUTPUT_PREFIX}_{timestamp}.csv"
                st.dataframe(result_df.head(10), use_container_width=True)
                csv_output = result_df.to_csv(index=False).encode('utf-8')
                st.download_button("✅ Scarica File Elaborato", csv_output, output_filename,
                                   "text/csv", type="primary")
                st.success("Elaborazione completata con successo!")
            else:
                st.warning("Nessuna riga da aggiornare o nessun risultato generato.")
        except Exception as e:
            st.error("Errore critico durante l'elaborazione:")
            st.exception(e)
