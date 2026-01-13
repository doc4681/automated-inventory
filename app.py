import streamlit as st
import pandas as pd
from datetime import datetime
from logic import (
    process_inventory, OUTPUT_PREFIX, VALID_TRADEMARKS,
    COL_SHOPIFY_SKU, COL_SHOPIFY_QTY
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

# Layout a colonne
col_upload, col_info = st.columns([1, 1])

with col_upload:
    st.markdown('<div class="sub-header">1. Carica i File</div>', unsafe_allow_html=True)
    
    # File upload con validazione
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

with col_info:
    st.markdown('<div class="sub-header">2. Configurazione</div>', unsafe_allow_html=True)
    
    # Informazioni sui trademark
    with st.expander("ℹ️ Trademark Validi Configurati"):
        st.write(f"**Totale brand configurati:** {len(VALID_TRADEMARKS)}")
        st.write(", ".join(sorted(VALID_TRADEMARKS)))
    
    # Spiegazione processo
    st.markdown("""
    <div class="info-box">
    <b>Come funziona:</b><br>
    1. Carica i 3 file CSV<br>
    2. Clicca "Avvia Elaborazione"<br>
    3. Scarica il file aggiornato<br>
    4. Importa in Shopify
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# ELABORAZIONE
# ==========================================

st.markdown("---")

# Verifica se tutti i file sono caricati
ready_to_process = file_shopify is not None and file_mcws is not None and file_bbr is not None

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
            st.info("👆 Carica tutti i file e clicca 'Avvia Sincronizzazione'")
    
    if process_btn:
        with st.spinner('Elaborazione in corso...'):
            try:
                # Leggi i file caricati
                df_shopify = load_dataframe(file_shopify)
                df_mcws = load_dataframe(file_mcws)
                df_bbr = load_dataframe(file_bbr)
                
                # Esegui la logica di processing
                result_df, stats, duplicate_report, log_messages = process_inventory(
                    df_shopify, df_mcws, df_bbr
                )
                
                # ==========================================
                # RISULTATI
                # ==========================================
                
                st.markdown("---")
                st.markdown('<div class="sub-header">4. Risultati</div>', unsafe_allow_html=True)
                
                if result_df is not None and len(result_df) > 0:
                    # Metriche
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
                    L'inventario Shopify è già sincronizzato con i listini fornitori.
                    </div>
                    """, unsafe_allow_html=True)
                    st.balloons()
                
            except Exception as e:
                st.error(f"Si è verificato un errore durante l'elaborazione:")
                st.exception(e)
                
else:
    # Mostra istruzioni quando i file non sono ancora caricati
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

# Footer
st.markdown("---")
st.caption("🔧 Inventory Sync WebApp v1.0 | Sviluppato con Streamlit")
