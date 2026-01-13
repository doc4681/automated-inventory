import pandas as pd
import re
from collections import defaultdict

# ==========================================
# CONFIGURAZIONE
# ==========================================

# --- COLONNE ATTESE NEI FILE ---
# 1. SHOPIFY (Target)
COL_SHOPIFY_SKU = 'Variant SKU'
COL_SHOPIFY_QTY = 'Variant Inventory Qty'

# 2. MCWS (Source A)
COL_MCWS_OUR_CODE = 'Our Code'
COL_MCWS_CODE = 'Code'
COL_MCWS_TRADEMARK = 'Trademark'

# 3. BBR (Source B)
COL_BBR_SKU = 'DescrizioneVariante'
COL_BBR_QTY = 'QtaResidua'

# --- TRADEMARK FILTER ---
# Lista di trademark validi da considerare
VALID_TRADEMARKS = [
    'ACME-MODELS', 'ALERTE', 'AUTOART', 'AVENUE43', 'BBR-MODELS', 'BURAGO',
    'CMC', 'CMR', 'ELIGOR', 'ESVAL MODEL', 'GP-REPLICAS', 'GT-SPIRIT',
    'IXO-MODELS', 'KK-SCALE', 'KYOSHO', 'LCD-MODEL', 'LOOKSMART', 'MAXIMA',
    'MINI HELMET', 'MINICHAMPS', 'MITICA', 'MITICA-DIECAST', 'MITICA-R',
    'MOTORHELIX', 'MR-MODELS', 'NOREV', 'NZG', 'OTTO-MOBILE', 'RIO-MODELS',
    'SCHUCO', 'SOLIDO', 'SPARK-MODEL', 'STAMP-MODELS', 'TECNOMODEL',
    'TOPMARQUES', 'TROFEU', 'TRUESCALE', 'WERK83', 'DM-MODELS',
    'UNIVERSAL HOBBIES', 'LS-COLLECTIBLES', 'MCG', 'SUN-STAR'
]

OUTPUT_PREFIX = 'INVENTORY_UPDATE'

# ==========================================
# FUNZIONI DI UTILITA
# ==========================================

def clean_code(code):
    """Normalizza code: Uppercase, rimuove special chars (k-123 -> K123)"""
    if pd.isna(code) or code == '':
        return ""
    s = str(code).strip().upper()
    s = re.sub(r'[^A-Z0-9]', '', s)
    return s.lstrip('0')


def clean_trademark(trademark):
    """Normalizza trademark: Uppercase, rimuove spazi extra"""
    if pd.isna(trademark) or trademark == '':
        return ""
    return str(trademark).strip().upper()


def find_duplicate_codes_with_trademark_check(df_mcws, code_col, trademark_col):
    """
    Trova codici duplicati e verifica trademark.
    Ritorna: valid_rows_indices, duplicate_report
    """
    code_groups = defaultdict(list)
    
    for idx, row in df_mcws.iterrows():
        code = clean_code(row[code_col])
        if not code:
            continue
        code_groups[code].append(idx)
    
    duplicates = {code: indices for code, indices in code_groups.items() if len(indices) > 1}
    
    valid_trademark_rows = []
    duplicate_report = []
    
    for code, indices in duplicates.items():
        for idx in indices:
            row = df_mcws.iloc[idx]
            trademark = clean_trademark(row.get(trademark_col, ''))
            
            if trademark in VALID_TRADEMARKS:
                valid_trademark_rows.append(idx)
            
            duplicate_report.append({
                'Code': code,
                'Row_Index': idx + 1,
                'Trademark': trademark,
                'Is_Valid_Trademark': trademark in VALID_TRADEMARKS
            })
    
    return valid_trademark_rows, duplicate_report


def process_inventory(shopify_df, mcws_df, bbr_df):
    """
    Processa i 3 file e genera il report di aggiornamento.
    Ritorna: df_output, stats, duplicate_report, log_messages
    """
    log_messages = []
    duplicate_report = []
    stats = {'total': 0, 'updates_1': 0, 'updates_0': 0}
    rows_output = []
    processed_skus = set()
    
    log_messages.append(f"Trademark validi: {len(VALID_TRADEMARKS)} brand")
    
    # ==========================================
    # 1. PROCESS MCWS (con filtro trademark e gestione duplicati)
    # ==========================================
    log_messages.append("1. Processing MCWS Stocklist...")
    
    available_skus = set()
    
    # Verifica se esiste la colonna Trademark
    has_trademark = COL_MCWS_TRADEMARK in mcws_df.columns
    if has_trademark:
        log_messages.append("   Colonna Trademark trovata, applicazione filtro brand validi")
    else:
        log_messages.append("   ATTENZIONE: Colonna Trademark non trovata in MCWS")
        log_messages.append("   Verranno elaborati TUTTI i prodotti senza filtro Trademark")
    
    # GESTIONE DUPLICATI
    if has_trademark:
        log_messages.append("   Verifica duplicati...")
        valid_duplicate_rows, duplicate_report = find_duplicate_codes_with_trademark_check(
            mcws_df, COL_MCWS_OUR_CODE, COL_MCWS_TRADEMARK
        )
        log_messages.append(f"   Trovati {len(duplicate_report)} casi di duplicati")
    
    # ELABORAZIONE STANDARD con filtro Trademark
    log_messages.append("   Elaborazione codici da MCWS...")
    
    # Processa colonna 'Our Code'
    if COL_MCWS_OUR_CODE in mcws_df.columns:
        for idx, code in enumerate(mcws_df[COL_MCWS_OUR_CODE]):
            c = clean_code(code)
            if not c:
                continue
            
            if has_trademark:
                trademark = clean_trademark(mcws_df.iloc[idx][COL_MCWS_TRADEMARK])
                if trademark not in VALID_TRADEMARKS:
                    continue
            
            available_skus.add(c)
    
    # Processa colonna 'Code'
    if COL_MCWS_CODE in mcws_df.columns:
        for idx, code in enumerate(mcws_df[COL_MCWS_CODE]):
            c = clean_code(code)
            if not c:
                continue
            
            if has_trademark:
                trademark = clean_trademark(mcws_df.iloc[idx][COL_MCWS_TRADEMARK])
                if trademark not in VALID_TRADEMARKS:
                    continue
            
            available_skus.add(c)
    
    log_messages.append(f"   Caricati {len(available_skus)} codici unici da MCWS")
    
    # ==========================================
    # 2. PROCESS BBR
    # ==========================================
    log_messages.append("2. Processing BBR Export...")
    
    count_start = len(available_skus)
    
    if COL_BBR_SKU in bbr_df.columns:
        for index, row in bbr_df.iterrows():
            is_available = True
            
            if COL_BBR_QTY in bbr_df.columns:
                try:
                    qty = float(str(row[COL_BBR_QTY]).replace(',', '.'))
                    if qty <= 0:
                        is_available = False
                except:
                    pass
            
            if is_available:
                code = row[COL_BBR_SKU]
                c = clean_code(code)
                if c:
                    available_skus.add(c)
    
    log_messages.append(f"   Caricati {len(available_skus) - count_start} codici unici da BBR")
    log_messages.append(f"   TOTALE MASTER SKU LIST: {len(available_skus)} item unici")
    
    # ==========================================
    # 3. COMPARE SHOPIFY
    # ==========================================
    log_messages.append("3. Comparing with Shopify Products...")
    
    if COL_SHOPIFY_SKU not in shopify_df.columns:
        log_messages.append(f"ERRORE: Colonna '{COL_SHOPIFY_SKU}' mancante nel file Shopify")
        return None, stats, duplicate_report, log_messages
    
    for idx, row in shopify_df.iterrows():
        stats['total'] += 1
        
        raw_sku = row.get(COL_SHOPIFY_SKU, '')
        sku_clean = clean_code(raw_sku)
        
        if not sku_clean: # COMMENTATO: or sku_clean.startswith("KK")or sku_clean.startswith("KK")
            continue
        if sku_clean in processed_skus:
            continue
        processed_skus.add(sku_clean)
        
        # Get current Shopify Qty
        try:
            current_val = float(row.get(COL_SHOPIFY_QTY, 0))
        except:
            current_val = 0
        
        current_logic = 1 if current_val > 0 else 0
        
        # Check match in master list
        is_in_stock_list = sku_clean in available_skus
        
        new_qty = None
        
        if is_in_stock_list and current_logic == 0:
            new_qty = 1
            stats['updates_1'] += 1
        elif not is_in_stock_list and current_logic == 1:
            new_qty = 0
            stats['updates_0'] += 1
        
        if new_qty is not None:
            out_row = row.copy()
            out_row[COL_SHOPIFY_QTY] = new_qty
            rows_output.append(out_row)
    
    log_messages.append(f"   Totale SKU processati: {len(processed_skus)}")
    log_messages.append(f"   Aggiornamenti necessari: To 1={stats['updates_1']}, To 0={stats['updates_0']}")
    
    df_output = pd.DataFrame(rows_output) if rows_output else pd.DataFrame()
    
    return df_output, stats, duplicate_report, log_messages
