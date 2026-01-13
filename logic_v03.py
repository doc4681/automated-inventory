"""
logic_v03.py - Inventory Sync con Gestione Dinamica Costi e Prezzi
Versione aggiornata e DEFINITIVA:
1. Identifica i prodotti BBR tramite i TAGS (perché non c'è colonna Trademark).
2. Esclusione BBR da MCWS (Se è BBR, ignora MCWS).
3. Double Check SKU + BRAND per MCWS (Evita collisioni SKU su brand diversi).
4. ***NORMALIZZAZIONE TRADEMARK***: Gestisce "SUN-STAR" vs "SUN STAR" rimuovendo trattini e spazi ovunque.
"""

import pandas as pd
import numpy as np
import re
from io import StringIO

# ==========================================
# CONFIGURAZIONE COSTANTI
# ==========================================

OUTPUT_PREFIX = "INVENTORY_UPDATE_V03"

# Nomi colonne file Shopify (Products_all.csv)
COL_SHOPIFY_SKU = 'Variant SKU'
COL_SHOPIFY_QTY = 'Variant Inventory Qty'
COL_SHOPIFY_COST = 'Variant Cost'
COL_SHOPIFY_PRICE = 'Variant Price'
COL_SHOPIFY_TAGS = 'Tags'

# Colonne aggiuntive
COL_COSTO_BBR = 'CostoBBRModels'
COL_NET_PRICE = 'Net Price'
COL_CHANGE_LOG = 'Change Log'

# Mapping interno
COL_SKU = COL_SHOPIFY_SKU
COL_QTY = COL_SHOPIFY_QTY
COL_COST = COL_SHOPIFY_COST
COL_PRICE = COL_SHOPIFY_PRICE
COL_TAGS = COL_SHOPIFY_TAGS

# Colonne Fornitori
COL_BBR_SKU = 'DescrizioneVariante'
COL_BBR_COST = COL_COSTO_BBR
COL_BBR_QTY = 'QtaResidua'

COL_MCWS_NET = COL_NET_PRICE
COL_MCWS_CODE = 'Code'
COL_MCWS_TRADEMARK = 'Trademark'
COL_MCWS_BRAND = 'Trademark'

# Mantengo definizioni per compatibilità import app.py
COL_BRAND = 'Trademark' 
COL_MCWS_EAN = 'EAN'

# ==========================================
# FUNZIONI DI UTILITÀ
# ==========================================

def normalize_string(s):
    """
    Funzione CRUCIALE: Rimuove spazi, trattini e caratteri speciali.
    Converte tutto in maiuscolo.
    Es. "SUN-STAR" -> "SUNSTAR"
    Es. "Sun Star" -> "SUNSTAR"
    Es. "brand_Ferrari" -> "BRANDFERRARI"
    """
    if pd.isna(s):
        return ""
    # Maiuscolo e tieni solo caratteri alfanumerici (A-Z, 0-9)
    return re.sub(r'[^A-Z0-9]', '', str(s).upper())

def clean_currency(value):
    if pd.isna(value) or value == '':
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    val_str = str(value).replace('€', '').replace('$', '').strip()
    if ',' in val_str and '.' in val_str:
        val_str = val_str.replace('.', '').replace(',', '.')
    elif ',' in val_str:
        val_str = val_str.replace(',', '.')
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def clean_qty(value):
    try:
        num = pd.to_numeric(value, errors='coerce')
        if pd.isna(num):
            return 0
        return int(num)
    except:
        return 0

def check_brand_compatibility(shopify_tags, supplier_brand):
    """
    Verifica se il Brand del fornitore è presente nei TAG di Shopify.
    Usa la normalizzazione per ignorare trattini e spazi.
    """
    if pd.isna(supplier_brand) or not str(supplier_brand).strip():
        return True # Fallback se manca brand fornitore
    
    if pd.isna(shopify_tags) or not str(shopify_tags).strip():
        return True # Fallback se mancano tag
    
    # Normalizza il brand del fornitore (es. "SUN-STAR" -> "SUNSTAR")
    norm_supplier = normalize_string(supplier_brand)
    
    # Analizza i tag
    tags_list = str(shopify_tags).split(',')
    for tag in tags_list:
        # Normalizza il tag (es. " Sun Star " -> "SUNSTAR")
        norm_tag = normalize_string(tag)
        
        # Rimuoviamo prefissi comuni tipo "BRAND" (es. "BRANDSUNSTAR" -> "SUNSTAR")
        norm_tag_clean = norm_tag.replace('BRAND', '') 
        
        # Confronto
        if norm_supplier == norm_tag or norm_supplier == norm_tag_clean:
            return True
        if norm_supplier in norm_tag: 
            return True
            
    return False

def load_markup_rules(markup_file_content):
    markup_dict = {}
    try:
        if hasattr(markup_file_content, 'read'):
            markup_file_content.seek(0)
            df = pd.read_csv(markup_file_content, sep='\t')
        else:
            return {}
        if 'TRADEMARK' in df.columns and 'Markup %' in df.columns:
            for _, row in df.iterrows():
                # Normalizziamo anche le chiavi del markup per sicurezza
                raw_brand = str(row['TRADEMARK'])
                norm_brand = normalize_string(raw_brand)
                
                markup_str = str(row['Markup %']).replace(',', '.')
                try:
                    markup_val = float(markup_str)
                    markup_dict[norm_brand] = markup_val # Usiamo chiave normalizzata
                except:
                    continue
    except Exception as e:
        print(f"Errore caricamento markup: {e}")
        # Default fallback
        markup_dict['BBR'] = 1.75
    return markup_dict

def load_trademarks(file_obj):
    """
    Carica la lista marchi e restituisce un set di stringhe NORMALIZZATE.
    Es. File contiene "SUN-STAR", set conterrà "SUNSTAR".
    """
    trademarks = set()
    try:
        if hasattr(file_obj, 'read'):
            file_obj.seek(0)
            content = file_obj.read()
            if isinstance(content, bytes):
                content = content.decode('utf-8')
            lines = content.splitlines()
            for line in lines:
                tm = line.strip()
                if tm:
                    # SALVA LA VERSIONE NORMALIZZATA
                    trademarks.add(normalize_string(tm))
    except Exception as e:
        print(f"Errore caricamento trademarks: {e}")
    return trademarks

def get_markup_for_brand(tags, brand_name, markup_dict):
    """
    Recupera il markup usando chiavi normalizzate.
    """
    # 1. Prova col brand del fornitore normalizzato
    if brand_name:
        norm_brand = normalize_string(brand_name)
        if norm_brand in markup_dict:
            return markup_dict[norm_brand]
    
    # 2. Prova coi tag normalizzati
    if pd.notna(tags):
        tags_list = [t.strip() for t in str(tags).split(',')]
        for tag in tags_list:
            norm_tag = normalize_string(tag)
            clean_tag = norm_tag.replace('BRAND', '')
            
            if clean_tag in markup_dict:
                return markup_dict[clean_tag]
            if norm_tag in markup_dict:
                return markup_dict[norm_tag]
    
    return 1.50

# ==========================================
# LOGICA PRINCIPALE (V03)
# ==========================================
def process_inventory_v03(df_shopify, df_mcws, df_bbr, markup_file, valid_trademarks_file):
    """
    Elabora l'inventario filtrando per marchi validi e gestendo priorità BBR.
    Usa normalizzazione stringhe per matching sicuro (ignora spazi/trattini).
    """
    
    # --- 1. PREPARAZIONE DATI ---
    
    markup_rules = load_markup_rules(markup_file)
    valid_trademarks_normalized = load_trademarks(valid_trademarks_file)
    
    # BBR Lookup
    bbr_lookup = {}
    if not df_bbr.empty:
        df_bbr.columns = [c.strip() for c in df_bbr.columns]
        for _, row in df_bbr.iterrows():
            sku = str(row.get(COL_BBR_SKU, '')).strip()
            if sku:
                qty_val = clean_qty(row.get(COL_BBR_QTY, 0))
                cost_val = clean_currency(row.get(COL_BBR_COST, 0))
                bbr_lookup[sku] = {
                    'cost': cost_val,
                    'qty': qty_val
                }

    # MCWS Lookup
    mcws_lookup = {}
    if not df_mcws.empty:
        df_mcws.columns = [c.strip().replace('"', '') for c in df_mcws.columns]
        for _, row in df_mcws.iterrows():
            
            raw_trademark = str(row.get(COL_MCWS_TRADEMARK, ''))
            norm_trademark = normalize_string(raw_trademark)
            
            # FILTRO TRADEMARK (Confronto su base Normalizzata)
            # Se la lista è vuota, passa tutto. Se c'è, filtra.
            if valid_trademarks_normalized and norm_trademark not in valid_trademarks_normalized:
                continue
                
            code = str(row.get(COL_MCWS_CODE, '')).strip()
            if code:
                mcws_lookup[code] = {
                    'cost': clean_currency(row.get(COL_MCWS_NET, 0)),
                    'qty': 999,
                    'brand': raw_trademark # Teniamo l'originale per riferimento
                }
    
    # Statistiche e Log
    stats = {
        'processed': 0, 'updated_qty': 0, 'updated_cost': 0, 'updated_price': 0, 'errors': 0, 
        'inventory': {'total': 0, 'updates_1': 0, 'updates_0': 0}
    }
    logs = []
    
    # --- 2. ELABORAZIONE SHOPIFY ---
    
    output_df = df_shopify.copy()
    if COL_CHANGE_LOG not in output_df.columns:
        output_df[COL_CHANGE_LOG] = ''
        
    for index, row in output_df.iterrows():
        try:
            stats['processed'] += 1
            stats['inventory']['total'] += 1
            
            sku = str(row.get(COL_SKU, '')).strip()
            tags = str(row.get(COL_TAGS, '')) # Tag originali
            
            current_qty = clean_qty(row.get(COL_QTY, 0))
            current_cost = clean_currency(row.get(COL_COST, 0))
            current_price = clean_currency(row.get(COL_PRICE, 0))
            
            new_qty = current_qty
            new_cost = current_cost
            new_price = current_price
            
            changes = []
            found_supplier = False
            supplier_brand = ""
            
            # --- LOGICA IDENTIFICAZIONE FORNITORE ---
            
            # 1. CONTROLLO PRIORITARIO BBR (File BBR_export)
            if sku in bbr_lookup:
                found_supplier = True
                supplier_data = bbr_lookup[sku]
                
                # Aggiorna BBR
                supplier_cost = supplier_data['cost']
                if supplier_cost > 0 and abs(supplier_cost - current_cost) > 0.01:
                    new_cost = supplier_cost
                    changes.append(f"COST(BBR): {current_cost:.2f}->{new_cost:.2f}")
                    stats['updated_cost'] += 1
                
                supplier_qty = supplier_data['qty']
                if supplier_qty != current_qty:
                    new_qty = supplier_qty
                    changes.append(f"QTY(BBR): {current_qty}->{new_qty}")
                    stats['updated_qty'] += 1
                    
                supplier_brand = "BBR"

            # 2. CONTROLLO MCWS (Solo se NON trovato in BBR)
            elif not found_supplier:
                
                # Check Esclusione BBR via Tag (Normalizzato)
                # Controlla se "BBR" è contenuto nei tag normalizzati
                tags_norm = normalize_string(tags)
                is_bbr_tag = 'BBR' in tags_norm
                
                if is_bbr_tag:
                    pass # Ignora, è un BBR orfano
                else:
                    # Check MCWS
                    match_obj = None
                    if sku in mcws_lookup:
                        match_obj = mcws_lookup[sku]
                    
                    if match_obj:
                        mcws_brand = match_obj['brand']
                        
                        # ===> DOUBLE CHECK DI SICUREZZA: SKU + BRAND <===
                        # Normalizza entrambi i lati prima di confrontare
                        if check_brand_compatibility(tags, mcws_brand):
                            found_supplier = True
                            supplier_brand = mcws_brand
                            
                            # Aggiorna Costo MCWS
                            supplier_cost = match_obj['cost']
                            if supplier_cost > 0 and abs(supplier_cost - current_cost) > 0.01:
                                new_cost = supplier_cost
                                changes.append(f"COST(MCWS): {current_cost:.2f}->{new_cost:.2f}")
                                stats['updated_cost'] += 1
                            
                            # Aggiorna Qta MCWS
                            if current_qty == 0:
                                new_qty = 1 
                                changes.append(f"QTY(MCWS): 0->1")
                                stats['updated_qty'] += 1
                        else:
                            # Collisione SKU rilevata (Brand diversi) -> Skip
                            pass

            # --- 3. AGGIORNAMENTO PREZZI ---
            if abs(new_cost - current_cost) > 0.01:
                if found_supplier:
                    markup = get_markup_for_brand(tags, supplier_brand, markup_rules)
                else:
                    markup = 1.5 
                
                calculated_price = round(new_cost * markup, 2)
                if abs(calculated_price - current_price) > 0.01:
                    new_price = calculated_price
                    changes.append(f"PRICE: {current_price:.2f}->{new_price:.2f}")
                    stats['updated_price'] += 1

            # --- 4. SALVATAGGIO ---
            output_df.at[index, COL_QTY] = new_qty
            output_df.at[index, COL_COST] = new_cost
            output_df.at[index, COL_PRICE] = new_price
            
            if new_qty > 0 and current_qty == 0:
                stats['inventory']['updates_1'] += 1
            elif new_qty == 0 and current_qty > 0:
                stats['inventory']['updates_0'] += 1
            
            if changes:
                output_df.at[index, COL_CHANGE_LOG] = " | ".join(changes)

        except Exception as e:
            stats['errors'] += 1
            logs.append(f"Errore riga {index} (SKU {row.get(COL_SKU, 'NA')}): {str(e)}")

    stats['total_rows'] = stats['processed']
    stats['qty_changes'] = stats['updated_qty']
    stats['cost_changes'] = stats['updated_cost']

    return output_df, stats, [], logs
