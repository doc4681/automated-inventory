import streamlit as st
import pandas as pd
from datetime import datetime
import os

# Import logica originale (Legacy)
from logic import (
    process_inventory, OUTPUT_PREFIX as OUTPUT_PREFIX_LEGACY, VALID_TRADEMARKS,
    COL_SHOPIFY_SKU, COL_SHOPIFY_QTY
)
# Import nuova logica (V03)
from logic_v03 import (
    process_inventory_v03, OUTPUT_PREFIX as OUTPUT_PREFIX_V03,
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

# ==========================================
# ICONE PERSONALIZZATE PER IOS HOME SCREEN
# ==========================================

st.markdown("""
<link rel="apple-touch-icon" href="/icon.png">
<link rel="apple-touch-icon-precomposed" href="/icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Inventory Sync">
""", unsafe_allow_html=True)

# CSS personalizzato
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1E88E5;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.5rem;
        font-weight: 600;
        color: #424242;
        margin-top: 1.5rem;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #E8F5E9;
        border-left: 4px solid #4CAF50;
    }
    .warning-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #FFF3E0;
        border-left: 4px solid #FF9800;
    }
    .info-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #1c1c1c;
        border-left: 4px solid #2196F3;
    }
    .metric-card {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #FAFAFA;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

def load_dataframe(uploaded_file):
    """
    Carica un file CSV, XLS o XLSX in un DataFrame pandas.
    """
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
# SELEZIONE MODALITÀ DI ELABORAZIONE
# ==========================================

if 'process_mode' not in st.session_state:
    st.session_state['process_mode'] = "Formato Originale (3 file)"

st.markdown('<div class="sub-header">0. Seleziona Formato</div>', unsafe_allow_html=True)

process_mode = st.radio(
    "Scegli il formato di elaborazione:",
    ["Formato Originale (3 file)", "Formato V03 (1 file Products.csv)"],
    index=0 if st.session_state['process_mode'] == "Formato Originale (3 file)" else 1,
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
# INTERFACCIA UPLOAD FILES
# ==========================================

col_upload, col_info = st.columns([1, 1])

with col_upload:
    st.markdown('<div class="sub-header">1. Carica i File</div>', unsafe_allow_html=True)
    
    if process_mode == "Formato Originale (3 file)":
        st.info("📄 **Formato Originale**: Carica i 3 file separati")
        
        file_shopify = st.file_uploader(
            "📁 **Shopify_Products.csv** (6 colonne)",
            type=["csv"],
            key="file_shopify",
            help="File export prodotti Shopify standard"
        )
        
        file_mcws = st.file_uploader(
            "📁 **MCWS_stocklist.csv**",
            type=["csv"],
            key="file_mcws",
            help="Listino MCWS"
        )
        
        file_bbr = st.file_uploader(
            "📁 **BBR_export**",
            type=["csv", "xls", "xlsx"],
            key="file_bbr",
            help="Export BBR"
        )
        
        files_loaded = (
            (file_shopify is not None) and 
            (file_mcws is not None) and 
            (file_bbr is not None)
        )
        
        OUTPUT_PREFIX = OUTPUT_PREFIX_LEGACY
        
    else:
        st.info("📦 **Formato V03**: Carica i 3 file (Products.csv ha 12 colonne)")
        
        file_shopify = st.file_uploader(
            "📁 **Products.csv** (12 colonne)",
            type=["csv"],
            key="file_shopify",
            help="File export Shopify con 12 colonne"
        )
        
        file_mcws = st.file_uploader(
            "📁 **MCWS_stocklist.csv**",
            type=["csv"],
            key="file_mcws",
            help="Listino MCWS"
        )
        
        file_bbr = st.file_uploader(
            "📁 **BBR_export**",
            type=["csv", "xls", "xlsx"],
            key="file_bbr",
            help="Export BBR"
        )
        
        files_loaded = (
            (file_shopify is not None) and 
            (file_mcws is not None) and 
            (file_bbr is not None)
        )
        
        OUTPUT_PREFIX = OUTPUT_PREFIX_V03

with col_info:
    st.markdown('<div class="sub-header">2. Configurazione</div>', unsafe_allow_html=True)
    
    if process_mode == "Formato Originale (3 file)":
        with st.expander("ℹ️ Trademark Validi Configurati"):
            st.write(f"**Totale brand configurati:** {len(VALID_TRADEMARKS)}")
            st.write(", ".join(sorted(VALID_TRADEMARKS)))
    
    if process_mode == "Formato Originale (3 file)":
        st.markdown("""
        <div class="info-box">
        <b>Come funziona:</b><br>
        1. Carica i 3 file CSV<br>
        2. Clicca "Avvia Elaborazione"<br>
        3. Scarica il file aggiornato<br>
        4. Importa in Shopify
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="info-box">
        <b>Come funziona V03:</b><br>
        1. Carica il file Products.csv<br>
        2. Clicca "Avvia Elaborazione"<br>
        3. Il sistema calcola automaticamente:<br>
        &nbsp;&nbsp;• Costi da CostoBBRModels/Net Price<br>
        &nbsp;&nbsp;• Prezzi con markup dinamico<br>
        4. Scarica il file con sole variazioni<br>
        5. Importa in Shopify
        </div>
        """, unsafe_allow_html=True)

# ==========================================
# ELABORAZIONE
# ==========================================

st.markdown("---")

if files_loaded:
    st.markdown('<div class="sub-header">3. Elaborazione</div>', unsafe_allow_html=True)
    
    col_btn, col_status = st.columns([1, 2])
    
    with col_btn:
        process_btn = st.button(
            "🚀 **Avvia Sincronizzazione**",
            type="primary",
            use_container_width=True
        )
    
    with col_status:
        if not process_btn:
            if process_mode == "Formato Originale (3 file)":
                st.info("👆 Carica tutti i 3 file e clicca 'Avvia Sincronizzazione'")
            else:
                st.info("👆 Carica il file Products.csv e clicca 'Avvia Sincronizzazione'")
    
    if process_btn:
        with st.spinner('Elaborazione in corso...'):
            try:
                if process_mode == "Formato Originale (3 file)":
                    # ==========================================
                    # ELABORAZIONE ORIGINALE (SOLO INVENTARIO)
                    # ==========================================
                    
                    df_shopify_loaded = load_dataframe(file_shopify)
                    df_mcws_loaded = load_dataframe(file_mcws)
                    df_bbr_loaded = load_dataframe(file_bbr)
                    
                    # Chiamata alla funzione originale (Logic)
                    # NOTA: qui salviamo in result_df per uniformità
                    result_df, stats, duplicate_report, log_messages = process_inventory(
                        df_shopify_loaded, df_mcws_loaded, df_bbr_loaded
                    )
                    
                    show_legacy_stats = True
                    
                else:
                    # ==========================================
                    # ELABORAZIONE V03 (COSTI + PREZZI)
                    # ==========================================
                    
                    df_shopify_loaded = load_dataframe(file_shopify)
                    df_mcws_loaded = load_dataframe(file_mcws)
                    df_bbr_loaded = load_dataframe(file_bbr)
                    
                    # APERTURA DEL FILE MARKUP LOCALE
                    with open('Vroomi_Markup.txt', 'r', encoding='utf-8') as f_markup:
                        result_df, stats, duplicate_report, log_messages = process_inventory_v03(
                            df_shopify_loaded, df_mcws_loaded, df_bbr_loaded, f_markup
                        )
                    
                    # Normalizza statistiche per visualizzazione legacy se necessario
                    if 'inventory' in stats:
                        stats_for_legacy = stats['inventory']
                    else:
                        stats_for_legacy = {'total': 0, 'updates_1': 0, 'updates_0': 0}
                    
                    show_legacy_stats = True
                
                # ==========================================
                # VISUALIZZAZIONE RISULTATI
                # ==========================================
                
                st.markdown("---")
                st.markdown('<div class="sub-header">4. Risultati</div>', unsafe_allow_html=True)
                
                if result_df is not None and len(result_df) > 0:
                    
                    # Metriche
                    m1, m2, m3, m4 = st.columns(4)
                    
                    # Se siamo in V03, stats ha una struttura diversa, adattiamo per la visualizzazione
                    if process_mode == "Formato Originale (3 file)":
                        total_sku = stats['total']
                        upd_1 = stats['updates_1']
                        upd_0 = stats['updates_0']
                    else:
                        # Estrazione stats V03
                        total_sku = stats['inventory']['total']
                        upd_1 = stats['inventory']['updates_1']
                        upd_0 = stats['inventory']['updates_0']

                    m1.metric("Totale SKU Shopify", total_sku)
                    m2.metric("Aggiornamenti → 1", upd_1, delta_color="normal")
                    m3.metric("Aggiornamenti → 0", upd_0, delta_color="inverse")
                    m4.metric("Totale Modifiche", upd_1 + upd_0)
                        
                    # Log di elaborazione
                    with st.expander("📋 Log Elaborazione"):
                        for msg in log_messages:
                            st.text(msg)
                        
                    # Report duplicati
                    if duplicate_report:
                        st.markdown('<div class="warning-box">', unsafe_allow_html=True)
                        st.markdown("**⚠️ Trovati duplicati nel listino MCWS:**")
                        df_duplicates = pd.DataFrame(duplicate_report)
                        st.dataframe(df_duplicates, use_container_width=True)
                        duplicate_csv = df_duplicates.to_csv(index=False).encode('utf-8')
                        st.download_button("📥 Scarica Report Duplicati", duplicate_csv, "duplicates_report.csv", "text/csv")
                        st.markdown('</div>', unsafe_allow_html=True)
                    
                    # Se V03, mostriamo metriche extra
                    if process_mode != "Formato Originale (3 file)":
                        st.write("---")
                        st.markdown("**Dettagli V03 (Costi/Prezzi):**")
                        c1, c2 = st.columns(2)
                        c1.metric("Variazioni Costo", stats.get('cost_changes', 0))
                        c2.metric("Variazioni Prezzo", stats.get('updated_price', 0))
                    
                    # Download
                    st.markdown("### 📥 Download")
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_filename = f"{OUTPUT_PREFIX}_{timestamp}.csv"
                    
                    st.markdown("**Anteprima prime 10 righe:**")
                    st.dataframe(result_df.head(10), use_container_width=True)
                    
                    csv_output = result_df.to_csv(index=False).encode('utf-8')
                    
                    st.download_button(
                        label="✅ **Scarica File Aggiornamento Inventario**",
                        data=csv_output,
                        file_name=output_filename,
                        mime="text/csv",
                        type="primary",
                        use_container_width=True
                    )
                    
                    # Istruzioni finali
                    st.success("Elaborazione completata con successo! Scarica il file CSV e importalo in Shopify.")
                    
                else:
                    st.balloons()
                    st.success("✅ Nessun aggiornamento necessario! L'inventario è già allineato.")
                
            except Exception as e:
                st.error("Si è verificato un errore durante l'elaborazione:")
                st.exception(e)

else:
    # Footer info se non sono caricati i file
    if process_mode == "Formato Originale (3 file)":
        st.markdown("""
        <div class="info-box">
        <b>📋 Prima di iniziare:</b><br>
        Assicurati di avere i 3 file CSV pronti:<br>
        • <b>Shopify_Products.csv</b><br>
        • <b>MCWS_stocklist.csv</b><br>
        • <b>BBR_export.csv</b>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="info-box">
        <b>📋 Prima di iniziare:</b><br>
        Assicurati di avere il file <b>Products.csv</b> pronto con 12 colonne.
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")
st.caption("🔧 Inventory Sync WebApp v2.1")
