import streamlit as st
import pandas as pd
from datetime import datetime
import os

# Import logica originale (Legacy)
from logic import (
    process_inventory, OUTPUT_PREFIX as OUTPUT_PREFIX_LEGACY,
    COL_SHOPIFY_SKU, COL_SHOPIFY_QTY
)
# Import nuova logica (V03 + Markup Only)
from logic_v03 import (
    process_inventory_v03, process_markup_only, OUTPUT_PREFIX as OUTPUT_PREFIX_V03,
    COL_SHOPIFY_SKU, COL_SHOPIFY_QTY, COL_SHOPIFY_COST, COL_SHOPIFY_PRICE,
    COL_SHOPIFY_TAGS, COL_COSTO_BBR, COL_NET_PRICE, COL_BRAND,
    COL_MCWS_CODE, COL_MCWS_TRADEMARK, COL_BBR_QTY, COL_CHANGE_LOG
)

# ==========================================
# CONFIGURAZIONE PAGINA
# ==========================================

st.set_page_config(
    page_title="Inventory Sync Manager",
    page_icon="icon.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<link rel="apple-touch-icon" href="/icon.png">
<link rel="apple-touch-icon-precomposed" href="/icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Inventory Sync">
""", unsafe_allow_html=True)

st.markdown("""
<style>
    .main-header { font-size: 2.5rem; font-weight: bold; color: #1E88E5; margin-bottom: 1rem; }
    .sub-header { font-size: 1.5rem; font-weight: 600; color: #424242; margin-top: 1.5rem; }
    .success-box { padding: 1rem; border-radius: 0.5rem; background-color: #E8F5E9; border-left: 4px solid #4CAF50; }
    .warning-box { padding: 1rem; border-radius: 0.5rem; background-color: #FFF3E0; border-left: 4px solid #FF9800; }
    .info-box { padding: 1rem; border-radius: 0.5rem; background-color: #1c1c1c; border-left: 4px solid #2196F3; }
    .metric-card { padding: 1rem; border-radius: 0.5rem; background-color: #FAFAFA; text-align: center; }
</style>
""", unsafe_allow_html=True)

def load_dataframe(uploaded_file):
    import os
    filename = uploaded_file.name.lower()
    _, ext = os.path.splitext(filename)
    try:
        if ext == '.csv':
            try:
                return pd.read_csv(uploaded_file, dtype=str)
            except:
                uploaded_file.seek(0)
                return pd.read_csv(uploaded_file, dtype=str, sep=';')
        elif ext in ['.xls', '.xlsx']:
            return pd.read_excel(uploaded_file, dtype=str)
        else:
            raise ValueError(f"Formato file non supportato: {ext}")
    except Exception as e:
        raise ValueError(f"Errore nella lettura del file {filename}: {str(e)}")

# ==========================================
# INTERFACCIA UTENTE
# ==========================================

st.markdown('<div class="main-header">📦 Inventory Sync WebApp</div>', unsafe_allow_html=True)
st.markdown("Carica i listini inventario per generare il file di aggiornamento per Shopify")
st.markdown("---")

# ==========================================
# SELEZIONE MODALITÀ
# ==========================================

if 'process_mode' not in st.session_state:
    st.session_state['process_mode'] = "Formato Originale (3 file)"

st.markdown('<div class="sub-header">0. Seleziona Formato</div>', unsafe_allow_html=True)

MODE_ORIGINAL = "Formato Originale (3 file)"
MODE_V03 = "Formato V03 (1 file Products.csv)"
MODE_MARKUP = "Adeguamento Markup (Solo Prezzi)"

process_mode = st.radio(
    "Scegli il formato di elaborazione:",
    [MODE_ORIGINAL, MODE_V03, MODE_MARKUP],
    index=0 if st.session_state['process_mode'] == MODE_ORIGINAL else (1 if st.session_state['process_mode'] == MODE_V03 else 2),
    horizontal=False
)

if process_mode != st.session_state['process_mode']:
    st.session_state['process_mode'] = process_mode
    for key in ['file_shopify', 'file_mcws', 'file_bbr', 'file_products']:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

st.markdown("---")

# ==========================================
# UPLOAD FILES
# ==========================================

col_upload, col_info = st.columns([1, 1])

with col_upload:
    st.markdown('<div class="sub-header">1. Carica i File</div>', unsafe_allow_html=True)
    
    if process_mode == MODE_ORIGINAL:
        st.info("📄 **Formato Originale**: Carica i 3 file separati")
        file_shopify = st.file_uploader("📁 **Shopify_Products.csv** (6 colonne)", type=["csv"], key="file_shopify")
        file_mcws = st.file_uploader("📁 **MCWS_stocklist.csv**", type=["csv"], key="file_mcws")
        file_bbr = st.file_uploader("📁 **BBR_export**", type=["csv", "xls", "xlsx"], key="file_bbr")
        files_loaded = (file_shopify and file_mcws and file_bbr)
        OUTPUT_PREFIX = OUTPUT_PREFIX_LEGACY
        
    elif process_mode == MODE_V03:
        st.info("📦 **Formato V03**: Carica i 3 file (Products.csv ha 12 colonne)")
        file_shopify = st.file_uploader("📁 **Products.csv** (12 colonne)", type=["csv"], key="file_shopify")
        file_mcws = st.file_uploader("📁 **MCWS_stocklist.csv**", type=["csv"], key="file_mcws")
        file_bbr = st.file_uploader("📁 **BBR_export**", type=["csv", "xls", "xlsx"], key="file_bbr")
        files_loaded = (file_shopify and file_mcws and file_bbr)
        OUTPUT_PREFIX = OUTPUT_PREFIX_V03
        
    elif process_mode == MODE_MARKUP:
        st.info("🏷️ **Adeguamento Markup**: Carica solo Products.csv")
        file_shopify = st.file_uploader("📁 **Products.csv** (12 colonne)", type=["csv"], key="file_shopify")
        files_loaded = (file_shopify is not None)
        OUTPUT_PREFIX = "MARKUP_UPDATE"

with col_info:
    st.markdown('<div class="sub-header">2. Configurazione</div>', unsafe_allow_html=True)
    
    # SELETTORE OUTPUT PER V03 (SOLO V03)
    only_changes_param = True # Default
    if process_mode == MODE_V03:
        output_scope = st.radio(
            "📂 **Seleziona Output:**",
            ["Solo Righe Modificate (Consigliato)", "File Intero Elaborato"],
            index=0
        )
        only_changes_param = (output_scope == "Solo Righe Modificate (Consigliato)")
        st.write("---")

    # OPZIONE CHANGE LOG (Solo per V03 e Markup)
    if process_mode != MODE_ORIGINAL:
        include_log = st.checkbox(
            "📝 **Includi colonna 'Change Log' nel file output**",
            value=True,
            help="Se selezionato, il file CSV finale includerà la colonna con i dettagli delle modifiche."
        )
    else:
        include_log = True

    st.write("---")
    
    try:
        with open('Valid_Trademarks.txt', 'r', encoding='utf-8') as f:
            trademarks_content = f.read().splitlines()
            valid_tms = [t for t in trademarks_content if t.strip()]
    except:
        valid_tms = []

    with st.expander(f"ℹ️ Trademark Validi (Caricati da file: {len(valid_tms)})"):
        if valid_tms:
            st.write(", ".join(valid_tms))
        else:
            st.warning("File Valid_Trademarks.txt non trovato o vuoto!")
    
    if process_mode == MODE_ORIGINAL:
        st.markdown("""<div class="info-box"><b>Formato Originale:</b><br>Sync solo quantità (3 file).</div>""", unsafe_allow_html=True)
    elif process_mode == MODE_V03:
        st.markdown("""<div class="info-box"><b>Formato V03:</b><br>Sync Quantità + Costi + Prezzi dinamici.</div>""", unsafe_allow_html=True)
    elif process_mode == MODE_MARKUP:
        st.markdown("""<div class="info-box"><b>Adeguamento Markup:</b><br>Ricalcola TUTTI i prezzi.<br>Output: File intero.</div>""", unsafe_allow_html=True)

#
