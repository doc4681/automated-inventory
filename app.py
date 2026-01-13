import streamlit as st
import pandas as pd
from datetime import datetime
from logic import (
    process_inventory, OUTPUT_PREFIX as OUTPUT_PREFIX_LEGACY, VALID_TRADEMARKS,
    COL_SHOPIFY_SKU, COL_SHOPIFY_QTY
)
from logic_v02 import (
    process_inventory_v02, OUTPUT_PREFIX as OUTPUT_PREFIX_V02,
    COL_SKU, COL_VARIANT_SKU, COL_VARIANT_QTY, COL_VARIANT_COST, COL_VARIANT_PRICE,
    COL_TAG, COL_COSTO_BBR, COL_NET_PRICE, COL_TRADEMARK, COL_BRAND, COL_CODE, COL_QTY
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

# CSS personalizzato per migliorare l'aspetto
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
    Gestisce automaticamente il formato basandosi sull'estensione.
    """
    import os
    
    # Estrai estensione del file
    filename = uploaded_file.name.lower()
    _, ext = os.path.splitext(filename)
    
    try:
        if ext == '.csv':
            # Prova prima con separatore standard, poi con punto e virgola
            try:
                return pd.read_csv(uploaded_file, dtype=str)
            except:
                uploaded_file.seek(0)  # Torna all'inizio del file
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

# Header principale
st.markdown('<div class="main-header">📦 Inventory Sync WebApp</div>', unsafe_allow_html=True)
st.markdown("Carica i listini inventario per generare il file di aggiornamento per Shopify")
st.markdown("---")

# ==========================================
# SELEZIONE MODALITÀ DI ELABORAZIONE
# ==========================================

st.markdown('<div class="sub-header">0. Seleziona Formato</div>', unsafe_allow_html=True)

col_mode_legacy, col_mode_v02 = st.columns(2)

with col_mode_legacy:
    st.markdown("""
    <div class="metric-card" style="border: 1px solid #4CAF50; background-color: #E8F5E9;">
    <h3 style="margin: 0; color: #2E7D32;">📄 Formato Originale</h3>
    <p style="margin: 0.5rem 0 0 0;">3 file separati</p>
    <p style="margin: 0; font-size: 0.8rem;">Shopify + MCWS + BBR</p>
    </div>
    """, unsafe_allow_html=True)

with col_mode_v02:
    st.markdown("""
    <div class="metric-card" style="border: 1px solid #2196F3; background-color: #E3F2FD;">
    <h3 style="margin: 0; color: #1565C0;">📦 Formato V02</h3>
    <p style="margin: 0.5rem 0 0 0;">File unificato</p>
    <p style="margin: 0; font-size: 0.8rem;">Products.csv (12 colonne)</p>
    </div>
    """, unsafe_allow_html=True)

# Selettore modalità
process_mode = st.radio(
    "Scegli il formato di elaborazione:",
    ["Formato Originale (3 file)", "Formato V02 (1 file Products.csv)"],
    horizontal=True,
    label_visibility="collapsed"
)

st.markdown("---")

# ==========================================
# INTERFACCIA UPLOAD FILES (Dinamica)
# ==========================================

col_upload, col_info = st.columns([1, 1])

with col_upload:
    st.markdown('<div class="sub-header">1. Carica i File</div>', unsafe_allow_html=True)
    
    if process_mode == "Formato Originale (3 file)":
        # Modalità Originale: 3 file separati
        file_shopify = st.file_uploader(
            "📁 **Shopify_Products.csv** (Target)",
            type=["csv"],
            help="File export prodotti Shopify con colonne 'Variant SKU' e 'Variant Inventory Qty'"
        )
        
        file_mcws = st.file_uploader(
            "📁 **MCWS_stocklist.csv** (Source A)",
            type=["csv"],
            help="Listino MCWS con colonne 'Our Code', 'Code' e 'Trademark'"
        )
        
        file_bbr = st.file_uploader(
            "📁 **BBR_export** (Source B)",
            type=["csv", "xls", "xlsx"],
            help="Export BBR (formato CSV, XLS o XLSX) con colonne 'DescrizioneVariante' e 'QtaResidua'"
        )
        
        files_loaded = file_shopify is not None and file_mcws is not None and file_bbr is not None
        
        OUTPUT_PREFIX = OUTPUT_PREFIX_LEGACY
        
    else:
        # Modalità V02: File unificato Products.csv
        file_products = st.file_uploader(
            "📁 **Products.csv** (File Unificato 12 colonne)",
            type=["csv"],
            help="File unificato con colonne: SKU, Variant SKU, Variant Inventory Qty, Variant Cost, Variant Price, Tag, CostoBBRModels, Net Price, Trademark, BRAND, Code, QTY"
        )
        
        files_loaded = file_products is not None
        
        OUTPUT_PREFIX = OUTPUT_PREFIX_V02

with col_info:
    st.markdown('<div class="sub-header">2. Configurazione</div>', unsafe_allow_html=True)
    
    if process_mode == "Formato Originale (3 file)":
        # Informazioni sui trademark (versione legacy)
        with st.expander("ℹ️ Trademark Validi Configurati"):
            st.write(f"**Totale brand configurati:** {len(VALID_TRADEMARKS)}")
            st.write(", ".join(sorted(VALID_TRADEMARKS)))
    
    # Spiegazione processo
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
        <b>Come funziona V02:</b><br>
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

if process_mode == "Formato Originale (3 file)":
    # Verifica se tutti i file sono caricati (formato legacy)
    ready_to_process = files_loaded
else:
    # Verifica se il file è caricato (formato V02)
    ready_to_process = files_loaded

if ready_to_process:
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
                    # ELABORAZIONE FORMATO LEGACY (3 file)
                    # ==========================================
                    
                    # Leggi i file caricati
                    df_shopify = load_dataframe(file_shopify)
                    df_mcws = load_dataframe(file_mcws)
                    df_bbr = load_dataframe(file_bbr)
                    
                    # Esegui la logica di processing (versione legacy)
                    result_df, stats, duplicate_report, log_messages = process_inventory(
                        df_shopify, df_mcws, df_bbr
                    )
                    
                    # Formato legacy: mostra statistiche originali
                    show_legacy_stats = True
                    
                else:
                    # ==========================================
                    # ELABORAZIONE FORMATO V02 (1 file)
                    # ==========================================
                    
                    # Leggi il file Products.csv
                    df_products = load_dataframe(file_products)
                    
                    # Esegui la logica di processing (versione V02)
                    result_df, stats = process_inventory_v02(df_products)
                    
                    # Formato V02: stats è un dizionario semplificato
                    show_legacy_stats = False
                
                # ==========================================
                # RISULTATI
                # ==========================================
                
                st.markdown("---")
                st.markdown('<div class="sub-header">4. Risultati</div>', unsafe_allow_html=True)
                
                if result_df is not None and len(result_df) > 0:
                    # Metriche
                    if show_legacy_stats:
                        # Statistiche formato legacy
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric(
                            "Totale SKU Shopify",
                            stats['total'],
                            help="Numero totale di SKU processati"
                        )
                        m2.metric(
                            "Aggiornamenti → 1",
                            stats['updates_1'],
                            delta_color="normal",
                            help="Prodotti da riattivare (erano a 0)"
                        )
                        m3.metric(
                            "Aggiornamenti → 0",
                            stats['updates_0'],
                            delta_color="inverse",
                            help="Prodotti da disattivare (avevano giacenza)"
                        )
                        m4.metric(
                            "Totale Modifiche",
                            stats['updates_1'] + stats['updates_0'],
                            help="Numero totale di righe da aggiornare"
                        )
                        
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
                            
                            # Download report duplicati
                            duplicate_csv = df_duplicates.to_csv(index=False).encode('utf-8')
                            st.download_button(
                                label="📥 Scarica Report Duplicati",
                                data=duplicate_csv,
                                file_name="duplicates_report.csv",
                                mime="text/csv"
                            )
                            st.markdown('</div>', unsafe_allow_html=True)
                    
                    else:
                        # Statistiche formato V02
                        m1, m2, m3 = st.columns(3)
                        m1.metric(
                            "Totale Righe",
                            stats.get('total_rows', len(result_df)),
                            help="Numero totale di righe processate"
                        )
                        m2.metric(
                            "Variazioni QTY",
                            stats.get('qty_changes', 'N/A'),
                            delta_color="normal",
                            help="Righe con variazione quantità"
                        )
                        m3.metric(
                            "Variazioni Costo",
                            stats.get('cost_changes', 'N/A'),
                            delta_color="normal",
                            help="Righe con variazione costo"
                        )
                        
                        # Verifica presenza Change Log
                        if 'Change Log' in result_df.columns:
                            with st.expander("📋 Change Log"):
                                for idx, row in result_df.iterrows():
                                    if pd.notna(row.get('Change Log')) and row['Change Log']:
                                        st.text(f"[{row.get(COL_VARIANT_SKU, 'N/A')}] {row['Change Log']}")
                    
                    # ==========================================
                    # DOWNLOAD
                    # ==========================================
                    st.markdown("### 📥 Download")
                    
                    # Genera nome file con timestamp
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_filename = f"{OUTPUT_PREFIX}_{timestamp}.csv"
                    
                    # Anteprima dati
                    st.markdown("**Anteprima prime 10 righe:**")
                    st.dataframe(result_df.head(10), use_container_width=True)
                    
                    # Download bottone principale
                    csv_output = result_df.to_csv(index=False).encode('utf-8')
                    
                    st.download_button(
                        label="✅ **Scarica File Aggiornamento Inventario**",
                        data=csv_output,
                        file_name=output_filename,
                        mime="text/csv",
                        type="primary",
                        use_container_width=True
                    )
                    
                    if process_mode == "Formato V02 (1 file Products.csv)":
                        st.markdown(f"""
                        <div class="success-box">
                        <b>💡 Note sul file V02:</b><br>
                        • Il file contiene SOLO le righe con variazioni di QTY o COSTO<br>
                        • Le righe con sole variazioni di prezzo sono state filtrate<br>
                        • Importa in Shopify → Products → Import
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
                        <div class="success-box">
                        <b>💡 Istruzioni per l'import in Shopify:</b><br>
                        1. Scarica il file CSV generato<br>
                        2. Vai in Shopify → Products → Import<br>
                        3. Carica il file e mappa le colonne<br>
                        4. Verifica l'anteprima e conferma
                        </div>
                        """, unsafe_allow_html=True)
                    
                else:
                    st.markdown("""
                    <div class="success-box">
                    ✅ <b>Nessun aggiornamento necessario!</b><br>
                    L'inventario è già sincronizzato con i listini fornitori.
                    </div>
                    """, unsafe_allow_html=True)
                    st.balloons()
                
            except Exception as e:
                st.error(f"Si è verificato un errore durante l'elaborazione:")
                st.exception(e)
                
else:
    # Mostra istruzioni quando i file non sono ancora caricati
    if process_mode == "Formato Originale (3 file)":
        st.markdown("""
        <div class="info-box">
        <b>📋 Prima di iniziare:</b><br>
        Assicurati di avere i 3 file CSV pronti:<br>
        • <b>Shopify_Products.csv</b> - Export prodotti da Shopify<br>
        • <b>MCWS_stocklist.csv</b> - Listino MCWS<br>
        • <b>BBR_export.csv</b> - Export BBR<br><br>
        <i>I file devono essere in formato CSV con le colonne attese come da configurazione.</i>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="info-box">
        <b>📋 Prima di iniziare:</b><br>
        Assicurati di avere il file <b>Products.csv</b> pronto con 12 colonne:<br>
        • SKU, Variant SKU, Variant Inventory Qty<br>
        • Variant Cost, Variant Price, Tag<br>
        • CostoBBRModels, Net Price, Trademark<br>
        • BRAND, Code, QTY<br><br>
        <i>Il file deve essere in formato CSV con le colonne attese.</i>
        </div>
        """, unsafe_allow_html=True)

# Footer
st.markdown("---")
st.caption("🔧 Inventory Sync WebApp v2.0 | Supporta: Formato Originale (3 file) + Formato V02 (Products.csv) | Sviluppato con Streamlit")
