"""
logic.py - Logica Originale (Legacy)
Aggiornata:
1. Legge i Trademark da file esterno.
2. PROTEZIONE PRE-ORDER: Se nei tag c'è "PRE-ORDER", la quantità non viene modificata.
3. TOGGLE BBR: Se enable_bbr=False, ignora il file BBR nel calcolo dello stock.
FIX pandas 3.x: usa dtype=object e row.to_dict() per evitare Arrow dtype errors.
"""

import pandas as pd
import re
from collections import defaultdict

# ==========================================
# CONFIGURAZIONE
# ==========================================

COL_SHOPIFY_SKU = 'Variant SKU'
COL_SHOPIFY_QTY = 'Variant Inventory Qty'
COL_SHOPIFY_TAGS = 'Tags'

COL_MCWS_OUR_CODE = 'Our Code'
COL_MCWS_CODE = 'Code'
COL_MCWS_TRADEMARK = 'Trademark'

COL_BBR_SKU = 'DescrizioneVariante'
COL_BBR_QTY = 'QtaResidua'

OUTPUT_PREFIX = "INVENTORY_UPDATE"

def clean_code(code):
    if pd.isna(code):
        return ""
    return str(code).strip()

def match_key(code):
    """
    Chiave di confronto tollerante agli zeri iniziali persi a monte
    (es. Shopify Products.csv con Variant SKU "3518" invece di "03518").
    Usata SOLO per il matching, non per i valori mostrati in output.
    """
    c = clean_code(code).upper()
    stripped = c.lstrip('0')
    return stripped if stripped else c

def normalize_string(s):
    if pd.isna(s):
        return ""
    return re.sub(r'[^A-Z0-9]', '', str(s).upper())

def load_trademarks(file_obj):
    trademarks = set()
    try:
        if hasattr(file_obj, 'read'):
            file_obj.seek(0)
            content = file_obj.read()
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

    log_messages = []

    # 0. VERIFICA TIPO DATI SKU/CODE (debug zeri iniziali)
    if not df_mcws.empty and COL_MCWS_CODE in df_mcws.columns:
        sample_mcws = df_mcws[COL_MCWS_CODE].dropna().astype(str).head(3).tolist()
        log_messages.append(f"[CHECK TIPO DATI] MCWS '{COL_MCWS_CODE}' dtype={df_mcws[COL_MCWS_CODE].dtype}, esempi={sample_mcws}")
    if not df_shopify.empty and COL_SHOPIFY_SKU in df_shopify.columns:
        sample_shop = df_shopify[COL_SHOPIFY_SKU].dropna().astype(str).head(3).tolist()
        log_messages.append(f"[CHECK TIPO DATI] Shopify '{COL_SHOPIFY_SKU}' dtype={df_shopify[COL_SHOPIFY_SKU].dtype}, esempi={sample_shop}")

    # 1. Carica Trademarks
    valid_trademarks = load_trademarks(trademarks_file)

    # 2. Crea Set di SKU Disponibili (Whitelist)
    available_skus = set()

    # --- Processa MCWS ---
    if not df_mcws.empty:
        df_mcws.columns = [c.strip().replace('"', '') for c in df_mcws.columns]

    duplicates = []
    seen_mcws = set()

    for _, row in df_mcws.iterrows():
        tm = str(row.get(COL_MCWS_TRADEMARK, '')).strip().upper()

        if valid_trademarks and tm not in valid_trademarks:
            continue

        code = clean_code(row.get(COL_MCWS_CODE, ''))

        if code:
            if code in seen_mcws:
                duplicates.append({'SKU': code, 'Brand': tm, 'List': 'MCWS'})
            seen_mcws.add(code)
            available_skus.add(match_key(code))

    # --- Processa BBR (Solo se abilitato) ---
    if enable_bbr and not df_bbr.empty:
        df_bbr.columns = [c.strip() for c in df_bbr.columns]

        for _, row in df_bbr.iterrows():
            sku = clean_code(row.get(COL_BBR_SKU, ''))
            try:
                qty = float(row.get(COL_BBR_QTY, 0))
            except:
                qty = 0

            if sku and qty > 0:
                available_skus.add(match_key(sku))

    # 3. Confronto con Shopify
    rows_output = []
    stats = {'total': 0, 'updates_1': 0, 'updates_0': 0}
    processed_skus = set()

    for index, row in df_shopify.iterrows():
        stats['total'] += 1
        raw_sku = row.get(COL_SHOPIFY_SKU, '')
        sku_clean = clean_code(raw_sku)

        if not sku_clean:
            continue

        if sku_clean in processed_skus:
            continue
        processed_skus.add(sku_clean)

        # --- CHECK PRE-ORDER ---
        tags = str(row.get(COL_SHOPIFY_TAGS, ''))
        tags_upper = tags.upper()
        norm_tags = normalize_string(tags)

        is_preorder = (
            'PRE-ORDER' in tags_upper or
            'PRE ORDER' in tags_upper or
            'PREORDER' in norm_tags
        )

        if is_preorder:
            continue

        # Get current Shopify Qty
        try:
            current_val = float(row.get(COL_SHOPIFY_QTY, 0))
        except:
            current_val = 0

        current_logic = 1 if current_val > 0 else 0

        # Check match in master list (tollerante a zeri iniziali persi)
        is_in_stock_list = match_key(sku_clean) in available_skus

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
            # FIX pandas 3.x: usa to_dict() per evitare Arrow dtype errors
            out_row = row.to_dict()
            out_row[COL_SHOPIFY_QTY] = str(new_qty)
            out_row['Change Log'] = change_log
            rows_output.append(out_row)
            log_messages.append(f"[{sku_clean}] {change_log}")

    # Crea DataFrame Output
    if rows_output:
        result_df = pd.DataFrame(rows_output)
    else:
        result_df = pd.DataFrame()

    return result_df, stats, duplicates, log_messages
