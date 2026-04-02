"""
logic.py - Logica Originale (Legacy)
Aggiornata:
1. Legge i Trademark da file esterno.
2. PROTEZIONE PRE-ORDER: Se nei tag c'è "PRE-ORDER", la quantità non viene modificata.
3. TOGGLE BBR: Se enable_bbr=False, ignora il file BBR nel calcolo dello stock.
"""

import pandas as pd
import re
from collections import defaultdict

# ==========================================
# CONFIGURAZIONE
# ==========================================

# --- COLONNE ATTESE NEI FILE ---
COL_SHOPIFY_SKU = 'Variant SKU'
COL_SHOPIFY_QTY = 'Variant Inventory Qty'
COL_SHOPIFY_TAGS = 'Tags'  # Necessario per il check Pre-Order

COL_MCWS_OUR_CODE = 'Our Code'
COL_MCWS_CODE = 'Code'
COL_MCWS_TRADEMARK = 'Trademark'

COL_BBR_SKU = 'DescrizioneVariante'
COL_BBR_QTY = 'QtaResidua'

# Prefisso file output
OUTPUT_PREFIX = "INVENTORY_UPDATE"

def clean_code(code):
    """Pulisce il codice SKU/EAN rimuovendo spazi e caratteri speciali."""
    if pd.isna(code):
        return ""
    return str(code).strip()

def normalize_string(s):
    """
    Rimuove spazi, trattini e caratteri speciali per confronto robusto.
    Es. "PRE-ORDER" -> "PREORDER"
    """
    if pd.isna(s):
        return ""
    return re.sub(r'[^A-Z0-9]', '', str(s).upper())

def load_trademarks(file_obj):
    """Carica la lista dei marchi validi dal file."""
    trademarks = set()
    try:
        if hasattr(file_obj, 'read'):
            file_obj.seek(0)
            content = file_obj.read()
            # Gestione sia stringhe che bytes
            if isinstance(content, bytes):
                content = content.decode('utf-8')
            
            lines = content.splitlines()
            for line in lines:
                tm = line.strip().upper()
                if tm:
                    trademarks.add(tm)
    except Exception as e:
        print(f"Errore caricamento trademarks: {e}")
    return trademarks

def process_inventory(df_shopify, df_mcws, df_bbr, trademarks_file, enable_bbr=True):
    """
    Logica originale:
    1. Filtra MCWS per marchi validi.
    2. Crea un set di SKU disponibili (MCWS + BBR se abilitato).
    3. Confronta con Shopify.
    4. PRE-ORDER: Se rilevato, ignora la riga (non cambia Qty).
    5. Genera file con SOLO le righe da aggiornare (0->1 o 1->0).
    """
    
    # 1. Carica Trademarks
    valid_trademarks = load_trademarks(trademarks_file)
    
    # 2. Crea Set di SKU Disponibili (Whitelist)
    available_skus = set()
    
    # --- Processa MCWS ---
    # Normalizza colonne rimuovendo spazi e apici
    if not df_mcws.empty:
        df_mcws.columns = [c.strip().replace('"', '') for c in df_mcws.columns]
        
    duplicates = []
    seen_mcws = set()

    for _, row in df_mcws.iterrows():
        tm = str(row.get(COL_MCWS_TRADEMARK, '')).strip().upper()
        
        # Filtro per Trademark
        if valid_trademarks and tm not in valid_trademarks:
            continue
            
        code = clean_code(row.get(COL_MCWS_CODE, ''))
        
        if code:
            if code in seen_mcws:
                duplicates.append({'SKU': code, 'Brand': tm, 'List': 'MCWS'})
            seen_mcws.add(code)
            available_skus.add(code)

    # --- Processa BBR (Solo se abilitato) ---
    if enable_bbr and not df_bbr.empty:
        # Normalizza colonne
        df_bbr.columns = [c.strip() for c in df_bbr.columns]
        
        for _, row in df_bbr.iterrows():
            sku = clean_code(row.get(COL_BBR_SKU, ''))
            try:
                qty = float(row.get(COL_BBR_QTY, 0))
            except:
                qty = 0
                
            if sku and qty > 0:
                available_skus.add(sku)

    # 3. Confronto con Shopify
    rows_output = []
    stats = {'total': 0, 'updates_1': 0, 'updates_0': 0}
    processed_skus = set()
    log_messages = []

    for index, row in df_shopify.iterrows():
        stats['total'] += 1
        raw_sku = row.get(COL_SHOPIFY_SKU, '')
        sku_clean = clean_code(raw_sku)
        
        if not sku_clean:
            continue
            
        if sku_clean in processed_skus:
            continue
        processed_skus.add(sku_clean)
        
        # --- CHECK PRE-ORDER (NUOVO) ---
        tags = str(row.get(COL_SHOPIFY_TAGS, ''))
        tags_upper = tags.upper()
        norm_tags = normalize_string(tags)
        
        # Controlla tutte le varianti possibili
        is_preorder = (
            'PRE-ORDER' in tags_upper or 
            'PRE ORDER' in tags_upper or 
            'PREORDER' in norm_tags
        )
        
        # Se è un pre-order, SALTA la riga.
        # Non aggiungendola a 'rows_output', Shopify non riceverà aggiornamenti per questo SKU.
        if is_preorder:
            continue

        # Get current Shopify Qty
        try:
            current_val = float(row.get(COL_SHOPIFY_QTY, 0))
        except:
            current_val = 0
        
        current_logic = 1 if current_val > 0 else 0
        
        # Check match in master list
        is_in_stock_list = sku_clean in available_skus
        
        new_qty = None
        change_log = ""
        
        if is_in_stock_list and current_logic == 0:
            new_qty = 1
            stats['updates_1'] += 1
            change_log = "QTY: 0->1 (RIATTIVATO)"
        elif not is_in_stock_list and current_logic == 1:
            new_qty = 0
            stats['updates_0'] += 1
            change_log = "QTY: 1->0 (DISATTIVATO)"
        
        if new_qty is not None:
            out_row = row.copy()
            out_row[COL_SHOPIFY_QTY] = str(new_qty)
            # Aggiungi colonna Change Log se non esiste, o appendi
            out_row['Change Log'] = change_log
            rows_output.append(out_row)
            log_messages.append(f"[{sku_clean}] {change_log}")

    # Crea DataFrame Output
    if rows_output:
        result_df = pd.DataFrame(rows_output)
    else:
        result_df = pd.DataFrame() # Vuoto

    return result_df, stats, duplicates, log_messages
