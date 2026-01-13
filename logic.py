"""
logic.py - Logica Originale (Legacy)
Aggiornata per leggere i Trademark da file esterno.
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

def process_inventory(df_shopify, df_mcws, df_bbr, valid_trademarks_file=None):
    """
    Processa l'inventario confrontando Shopify con MCWS e BBR.
    Restituisce un DataFrame con le modifiche da apportare.
    """
    
    # 1. Carica lista marchi validi
    valid_trademarks = set()
    if valid_trademarks_file:
        valid_trademarks = load_trademarks(valid_trademarks_file)
    
    # Se la lista è vuota (errore o file mancante), logga un warning ma procedi (o blocca se preferisci)
    # Qui assumiamo che se vuota, non filtra nulla (o filtra tutto? Meglio filtrare tutto per sicurezza)
    # Se vuoi che senza file accetti tutto, cambia logica. Qui manteniamo comportamento restrittivo.
    
    # 2. Creazione Dizionario Disponibilità (Set di SKU disponibili)
    available_skus = set()
    duplicate_report = []
    
    # A) Process BBR (Sempre validi)
    if not df_bbr.empty:
        df_bbr.columns = [c.strip() for c in df_bbr.columns]
        for _, row in df_bbr.iterrows():
            sku = clean_code(row.get(COL_BBR_SKU, ''))
            qty = pd.to_numeric(row.get(COL_BBR_QTY, 0), errors='coerce')
            if pd.isna(qty): qty = 0
            
            if sku and qty > 0:
                available_skus.add(sku)

    # B) Process MCWS (Filtrati per Trademark)
    mcws_codes_seen = set()
    
    if not df_mcws.empty:
        # Pulisci nomi colonne
        df_mcws.columns = [c.strip().replace('"', '') for c in df_mcws.columns]
        
        for _, row in df_mcws.iterrows():
            # Filtro Trademark
            trademark = str(row.get(COL_MCWS_TRADEMARK, '')).strip().upper()
            
            # SE ABBIAMO UNA LISTA E IL MARCHIO NON C'È, SALTA
            if valid_trademarks and trademark not in valid_trademarks:
                continue
                
            code = clean_code(row.get(COL_MCWS_CODE, ''))
            
            if code:
                # Check duplicati
                if code in mcws_codes_seen:
                    duplicate_report.append({
                        'Code': code,
                        'Trademark': trademark,
                        'Note': 'Duplicato nel file MCWS'
                    })
                mcws_codes_seen.add(code)
                
                # In Stocklist MCWS = Disponibile
                available_skus.add(code)

    # 3. Confronto con Shopify
    rows_output = []
    stats = {'total': 0, 'updates_1': 0, 'updates_0': 0}
    log_messages = []
    
    processed_skus = set()
    
    for idx, row in df_shopify.iterrows():
        stats['total'] += 1
        
        raw_sku = row.get(COL_SHOPIFY_SKU, '')
        sku_clean = clean_code(raw_sku)
        
        if not sku_clean:
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
            out_row[COL_SHOPIFY_QTY] = new_qty
            # Aggiungi colonna Change Log se non esiste, o appendi
            out_row['Change Log'] = change_log
            rows_output.append(out_row)
            log_messages.append(f"[{sku_clean}] {change_log}")
    
    # Creazione DataFrame Output
    if rows_output:
        df_output = pd.DataFrame(rows_output)
    else:
        df_output = pd.DataFrame(columns=df_shopify.columns)
        
    return df_output, stats, duplicate_report, log_messages
