"""
logic_v03.py - Inventory Sync con Gestione Dinamica Costi, Prezzi e SALE
Versione DEFINITIVA (Con Regole Markup per Fasce di Costo):
1. Identifica i prodotti BBR tramite TAGS.
2. PRE-ORDER: Rilevamento potenziato (QTA BLOCCATA, ma prezzi aggiornabili).
3. COSTI: Aggiorna solo se il fornitore ha un costo valido.
4. MARKUP DINAMICO (Logica Prioritaria):
   - Se Costo < 10€: Markup 2.2 (Priorità assoluta)
   - Se Costo < 20€: Markup 1.9 (Priorità assoluta)
   - Altrimenti: Markup da Brand (File TXT)
5. PREZZI & SALE: Logica dinamica (Check Universale) + Safety Check Shopify.
6. STOCK: Aggiorna BBR/MCWS solo se non è pre-order.
"""

import pandas as pd
import numpy as np
import re
from io import StringIO
import math

# ==========================================
# CONFIGURAZIONE COSTANTI
# ==========================================

OUTPUT_PREFIX = "INVENTORY_UPDATE_V03"

# --- CONFIGURAZIONE MARKUP BASSO COSTO ---
# Queste regole vincono su qualsiasi trademark
COST_THRESHOLD_LOW = 10.0   # Sotto questa cifra...
MARKUP_LOW = 2.2            # ...usa questo markup
COST_THRESHOLD_MID = 20.0   # Sotto questa cifra (ma sopra la Low)...
MARKUP_MID = 1.9            # ...usa questo markup

# Nomi colonne file Shopify (Products_all.csv)
COL_SHOPIFY_SKU = 'Variant SKU'
COL_SHOPIFY_QTY = 'Variant Inventory Qty'
COL_SHOPIFY_COST = 'Variant Cost'
COL_SHOPIFY_PRICE = 'Variant Price'
COL_SHOPIFY_COMPARE = 'Variant Compare At Price'
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
COL_COMPARE = COL_SHOPIFY_COMPARE
COL_TAGS = COL_SHOPIFY_TAGS

# Colonne Fornitori
COL_BBR_SKU = 'DescrizioneVariante'
COL_BBR_COST = COL_COSTO_BBR
COL_BBR_QTY = 'QtaResidua'

COL_MCWS_NET = COL_NET_PRICE
COL_MCWS_CODE = 'Code'
COL_MCWS_TRADEMARK = 'Trademark'
COL_MCWS_BRAND = 'Trademark'

COL_BRAND = 'Trademark' 
COL_MCWS_EAN = 'EAN'

# ==========================================
# FUNZIONI DI UTILITÀ
# ==========================================

def normalize_string(s):
    """Rimuove spazi, trattini e caratteri speciali."""
    if pd.isna(s):
        return ""
    return re.sub(r'[^A-Z0-9]', '', str(s).upper())

def clean_currency(value):
    """Pulisce e converte la valuta in float in modo sicuro."""
    if pd.isna(value) or value == '':
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
        
    val_str = str(value).replace('€', '').replace('$', '').strip()
    
    if ',' in val_str and '.' in val_str:
        if val_str.find(',') > val_str.find('.'):
            val_str = val_str.replace('.', '').replace(',', '.')
        else:
            val_str = val_str.replace(',', '')
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

def round_price_to_90(price):
    """Arrotonda il prezzo sempre per eccesso a .90."""
    if price <= 0:
        return 0.0
    integer_part = int(price)
    decimal_part = price - integer_part
    if decimal_part > 0.90001:
        return float(integer_part + 1.90)
    else:
        return float(integer_part + 0.90)

def add_sale_tag(tags_str):
    """Aggiunge ', SALE' ai tag se non esiste."""
    if pd.isna(tags_str): tags_str = ""
    tags_list = [t.strip() for t in str(tags_str).split(',') if t.strip()]
    if not any(t.upper() == 'SALE' for t in tags_list):
        tags_list.append("SALE")
    return ", ".join(tags_list)

def remove_sale_tag(tags_str):
    """Rimuove 'SALE' dai tag se esiste."""
    if pd.isna(tags_str): return ""
    tags_list = [t.strip() for t in str(tags_str).split(',') if t.strip()]
    new_list = [t for t in tags_list if t.upper() != 'SALE']
    return ", ".join(new_list)

def check_brand_compatibility(shopify_tags, supplier_brand):
    """Verifica coerenza Brand normalizzata."""
    if pd.isna(supplier_brand) or not str(supplier_brand).strip():
        return True 
    if pd.isna(shopify_tags) or not str(shopify_tags).strip():
        return True 
    
    norm_supplier = normalize_string(supplier_brand)
    tags_list = str(shopify_tags).split(',')
    for tag in tags_list:
        norm_tag = normalize_string(tag)
        norm_tag_clean = norm_tag.replace('BRAND', '') 
        
        if norm_supplier == norm_tag or norm_supplier == norm_tag_clean:
            return True
        if norm_supplier in norm_tag: 
            return True
            
    return False

def load_markup_rules(markup_file_content):
    """Carica le regole di markup in modo ROBUSTO."""
    markup_dict = {}
    default_markup = 1.50
    markup_dict['DEFAULT'] = default_markup
    
    try:
        if not hasattr(markup_file_content, 'read'):
            return markup_dict

        markup_file_content.seek(0)
        content = markup_file_content.read()
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
            
        lines = content.splitlines()
        header_idx = -1
        for i, line in enumerate(lines[:10]):
            if 'TRADEMARK' in line.upper() or 'BRAND' in line.upper():
                header_idx = i
                break
        
        if header_idx >= 0:
            for line in lines[header_idx+1:]:
                if not line.strip(): continue
                parts = line.replace('\t', ' ').split()
                if len(parts) >= 2:
                    mk_str = parts[-1].replace(',', '.').replace('%', '')
                    brand_str = " ".join(parts[:-1])
                    try:
                        val = float(mk_str)
                        markup_dict[normalize_string(brand_str)] = val
                    except:
                        continue
    except Exception as e:
        print(f"Errore caricamento markup: {e}")
        
    return markup_dict

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
                tm = line.strip()
                if tm:
                    trademarks.add(normalize_string(tm))
    except Exception as e:
        print(f"Errore caricamento trademarks: {e}")
    return trademarks

def get_markup_for_brand(tags, brand_name, markup_dict):
    """Recupera markup con fallback."""
    if brand_name:
        norm = normalize_string(brand_name)
        if norm in markup_dict: return markup_dict[norm]
        
    if pd.notna(tags):
        for tag in str(tags).split(','):
            norm = normalize_string(tag)
            clean = norm.replace('BRAND', '')
            if clean in markup_dict: return markup_dict[clean]
            if norm in markup_dict: return markup_dict[norm]
            
    return markup_dict.get('DEFAULT', 1.50)

# ==========================================
# HELPER: CALCOLO PREZZI CENTRALIZZATO
# ==========================================
def calculate_target_price_and_markup(cost, tags, supplier_brand, markup_rules, valid_trademarks_normalized):
    """
    Determina il markup e il prezzo target applicando la gerarchia delle regole:
    1. Costo < 10 -> Markup 2.2
    2. Costo < 20 -> Markup 1.9
    3. Costo >= 20 -> Markup da File (Brand)
    
    Restituisce: (target_price, markup_usato, motivo_stringa)
    """
    markup = 0.0
    reason = ""
    
    # 1. Regola Costo < 10
    if cost < COST_THRESHOLD_LOW:
        markup = MARKUP_LOW
        reason = "<10 Eur"
        
    # 2. Regola Costo < 20
    elif cost < COST_THRESHOLD_MID:
        markup = MARKUP_MID
        reason = "<20 Eur"
        
    # 3. Regola Brand Valido (Se costo >= 20)
    else:
        # Dobbiamo verificare se il brand è valido
        is_valid_brand = False
        
        # Se abbiamo un brand fornitore esplicito (da MCWS/BBR)
        if supplier_brand:
            # Assumiamo che se viene da un fornitore filtrato, è valido per il calcolo
            is_valid_brand = True
            
        # Se non abbiamo supplier_brand (es. Markup Only), controlliamo i tag
        if not is_valid_brand and pd.notna(tags):
            for tag in str(tags).split(','):
                norm = normalize_string(tag)
                clean = norm.replace('BRAND', '')
                if norm in valid_trademarks_normalized or clean in valid_trademarks_normalized:
                    is_valid_brand = True
                    break
        
        if is_valid_brand:
            markup = get_markup_for_brand(tags, supplier_brand, markup_rules)
            reason = "Brand Rules"
        else:
            # Se il brand non è riconosciuto e costo > 20,
            # in Markup Only non aggiorniamo (ritorna 0), 
            # in Inventory Sync usiamo default 1.5 se supplier trovato?
            # Manteniamo comportamento conservativo: se brand non valido, niente markup specifico.
            # Ma se c'è supplier_brand (quindi trovato nel listino), usiamo default.
            if supplier_brand:
                markup = 1.50
                reason = "Default (No Brand Match)"
            else:
                return 0.0, 0.0, "Skipped (No Brand)"

    # Calcolo Finale
    raw_price = cost * markup
    target_price = round_price_to_90(raw_price)
    
    return target_price, markup, reason

# ==========================================
# LOGICA PRINCIPALE (V03 - SYNC INVENTORY)
# ==========================================
def process_inventory_v03(df_shopify, df_mcws, df_bbr, markup_file, valid_trademarks_file, include_change_log=True, only_changes=True):
    
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
                bbr_lookup[sku] = {
                    'cost': clean_currency(row.get(COL_BBR_COST, 0)),
                    'qty': clean_qty(row.get(COL_BBR_QTY, 0))
                }

    # MCWS Lookup
    mcws_lookup = {}
    if not df_mcws.empty:
        df_mcws.columns = [c.strip().replace('"', '') for c in df_mcws.columns]
        for _, row in df_mcws.iterrows():
            raw_trademark = str(row.get(COL_MCWS_TRADEMARK, ''))
            norm_trademark = normalize_string(raw_trademark)
            
            if valid_trademarks_normalized and norm_trademark not in valid_trademarks_normalized:
                continue
                
            code = str(row.get(COL_MCWS_CODE, '')).strip()
            if code:
                mcws_lookup[code] = {
                    'cost': clean_currency(row.get(COL_MCWS_NET, 0)),
                    'qty': 999,
                    'brand': raw_trademark
                }
    
    stats = {
        'processed': 0, 'updated_qty': 0, 'updated_cost': 0, 'updated_price': 0, 'errors': 0, 
        'inventory': {'total': 0, 'updates_1': 0, 'updates_0': 0}
    }
    logs = []
    
    # --- 2. ELABORAZIONE SHOPIFY ---
    
    output_df = df_shopify.copy()
    if COL_CHANGE_LOG not in output_df.columns:
        output_df[COL_CHANGE_LOG] = ''
    
    if COL_COMPARE not in output_df.columns:
        output_df[COL_COMPARE] = ''

    for index, row in output_df.iterrows():
        try:
            stats['processed'] += 1
            stats['inventory']['total'] += 1
            
            sku = str(row.get(COL_SKU, '')).strip()
            tags = str(row.get(COL_TAGS, ''))
            
            # --- CHECK PRE-ORDER POTENZIATO ---
            tags_upper = tags.upper()
            norm_tags = normalize_string(tags)
            
            is_preorder = (
                'PRE-ORDER' in tags_upper or 
                'PRE ORDER' in tags_upper or 
                'PREORDER' in norm_tags
            )
            
            current_qty = clean_qty(row.get(COL_QTY, 0))
            current_cost = clean_currency(row.get(COL_COST, 0))
            current_price = clean_currency(row.get(COL_PRICE, 0))
            current_compare = row.get(COL_COMPARE, '')
            
            # Variabili di lavoro (Default = invariato)
            new_qty = current_qty
            new_cost = current_cost
            new_price = current_price
            new_compare = current_compare
            new_tags = tags
            
            changes = []
            found_supplier = False
            supplier_brand = ""
            
            # --- FASE 1: IDENTIFICAZIONE FORNITORE E AGG. DATI GREZZI ---
            
            # A. CHECK BBR
            if sku in bbr_lookup:
                found_supplier = True
                supplier_data = bbr_lookup[sku]
                supplier_brand = "BBR"
                
                # Costo BBR
                s_cost = supplier_data['cost']
                if s_cost > 0:
                    new_cost = s_cost
                    if abs(s_cost - current_cost) > 0.01:
                        changes.append(f"COST(BBR): {current_cost:.2f}->{new_cost:.2f}")
                        stats['updated_cost'] += 1
                
                # Qta BBR (BLOCCATA SE PRE-ORDER)
                if not is_preorder:
                    target_qty = 1 if supplier_data['qty'] > 0 else 0
                    if target_qty != current_qty:
                        new_qty = target_qty
                        changes.append(f"QTY(BBR-Force): {current_qty}->{new_qty}")
                        stats['updated_qty'] += 1

            # B. CHECK BBR ORFANO
            elif 'BBR' in norm_tags:
                # Stock (BLOCCATO SE PRE-ORDER)
                if not is_preorder and current_qty > 0:
                    new_qty = 0
                    changes.append(f"QTY(BBR-Missing): {current_qty}->0")
                    stats['updated_qty'] += 1

            # C. CHECK MCWS
            else:
                match_obj = mcws_lookup.get(sku)
                
                # C1. TROVATO IN MCWS
                if match_obj:
                    mcws_brand = match_obj['brand']
                    
                    if check_brand_compatibility(tags, mcws_brand):
                        found_supplier = True
                        supplier_brand = mcws_brand
                        
                        # Costo MCWS
                        s_cost = match_obj['cost']
                        if s_cost > 0:
                            new_cost = s_cost
                            if abs(s_cost - current_cost) > 0.01:
                                changes.append(f"COST(MCWS): {current_cost:.2f}->{new_cost:.2f}")
                                stats['updated_cost'] += 1
                        
                        # Qta MCWS (BLOCCATA SE PRE-ORDER)
                        if not is_preorder and current_qty == 0:
                            new_qty = 1
                            changes.append("QTY(MCWS): 0->1")
                            stats['updated_qty'] += 1
                            
                # C2. NON TROVATO IN MCWS (e non è BBR) -> STOCK A 0
                else:
                    if not is_preorder and current_qty > 0:
                        new_qty = 0
                        changes.append(f"QTY(Not in Stocklist): {current_qty}->0")
                        stats['updated_qty'] += 1

            # --- FASE 2: GESTIONE PREZZI E SALE (CHECK UNIVERSALE) ---
            
            if found_supplier and new_cost > 0:
                
                # USA HELPER CENTRALIZZATO
                target_price, markup, reason = calculate_target_price_and_markup(
                    new_cost, tags, supplier_brand, markup_rules, valid_trademarks_normalized
                )
                
                if target_price > 0:
                    # Confronta Target vs Attuale
                    
                    # CASO 1: SALE ACTIVATED (Target < Attuale)
                    if target_price < current_price:
                        if abs(target_price - current_price) > 0.01:
                            new_compare = current_price 
                            new_price = target_price    
                            new_tags = add_sale_tag(tags)
                            changes.append(f"SALE: {current_price:.2f}->{new_price:.2f} (Mk {markup} {reason})")
                            stats['updated_price'] += 1

                    # CASO 2: PRICE UP (Target > Attuale)
                    elif target_price > current_price:
                        if abs(target_price - current_price) > 0.01:
                            new_compare = "" 
                            new_price = target_price
                            new_tags = remove_sale_tag(tags)
                            changes.append(f"UP: {current_price:.2f}->{new_price:.2f} (Mk {markup} {reason})")
                            stats['updated_price'] += 1

            # --- FASE 3: SAFETY CHECK SHOPIFY ---
            val_compare = clean_currency(new_compare)
            if val_compare > 0 and new_price >= val_compare:
                new_compare = ""
                new_tags = remove_sale_tag(new_tags)
                if val_compare != clean_currency(current_compare) or "UP" not in str(changes):
                     changes.append(f"FIX: Price({new_price}) >= Compare({val_compare}) -> Sale Removed")

            # --- SALVATAGGIO ---
            output_df.at[index, COL_QTY] = new_qty
            output_df.at[index, COL_COST] = new_cost
            output_df.at[index, COL_PRICE] = new_price
            output_df.at[index, COL_COMPARE] = new_compare
            output_df.at[index, COL_TAGS] = new_tags
            
            if new_qty > 0 and current_qty == 0:
                stats['inventory']['updates_1'] += 1
            elif new_qty == 0 and current_qty > 0:
                stats['inventory']['updates_0'] += 1
            
            if changes:
                output_df.at[index, COL_CHANGE_LOG] = " | ".join(changes)

        except Exception as e:
            stats['errors'] += 1
            logs.append(f"Errore riga {index} SKU {row.get(COL_SKU)}: {e}")

    stats['total_rows'] = stats['processed']
    stats['qty_changes'] = stats['updated_qty']
    stats['cost_changes'] = stats['updated_cost']

    # === FILTRO FINALE ===
    if only_changes:
        final_df = output_df[output_df[COL_CHANGE_LOG] != '']
    else:
        final_df = output_df
    
    if not include_change_log:
        final_df = final_df.drop(columns=[COL_CHANGE_LOG], errors='ignore')

    return final_df, stats, [], logs


# ==========================================
# FUNZIONE: ADEGUAMENTO MARKUP ONLY
# ==========================================
def process_markup_only(df_shopify, markup_file, valid_trademarks_file):
    """
    Funzione indipendente per ricalcolare i prezzi di tutto il file.
    Usa la stessa logica di prezzo della V03.
    """
    markup_rules = load_markup_rules(markup_file)
    valid_trademarks_normalized = load_trademarks(valid_trademarks_file)
    
    stats = {'processed': 0, 'updated_price': 0, 'skipped': 0, 'errors': 0}
    logs = []
    
    output_df = df_shopify.copy()
    if COL_CHANGE_LOG not in output_df.columns:
        output_df[COL_CHANGE_LOG] = ''
    if COL_COMPARE not in output_df.columns:
        output_df[COL_COMPARE] = ''
        
    for index, row in output_df.iterrows():
        try:
            stats['processed'] += 1
            
            sku = str(row.get(COL_SKU, '')).strip()
            tags = str(row.get(COL_TAGS, ''))
            
            current_cost = clean_currency(row.get(COL_COST, 0))
            current_price = clean_currency(row.get(COL_PRICE, 0))
            current_compare = clean_currency(row.get(COL_COMPARE, 0))
            
            if current_cost <= 0:
                stats['skipped'] += 1
                continue
            
            # USA HELPER CENTRALIZZATO (Passiamo None come supplier_brand perché qui non lo sappiamo)
            target_price, markup, reason = calculate_target_price_and_markup(
                current_cost, tags, None, markup_rules, valid_trademarks_normalized
            )
            
            if target_price > 0:
                
                # Check Universale
                if target_price != current_price:
                    
                    # SALE
                    if target_price < current_price:
                        output_df.at[index, COL_COMPARE] = current_price
                        output_df.at[index, COL_PRICE] = target_price
                        new_tags = add_sale_tag(tags)
                        output_df.at[index, COL_TAGS] = new_tags
                        output_df.at[index, COL_CHANGE_LOG] = f"MK SALE: {current_price}->{target_price} ({reason})"
                    
                    # UP
                    else:
                        output_df.at[index, COL_COMPARE] = ""
                        output_df.at[index, COL_PRICE] = target_price
                        new_tags = remove_sale_tag(tags)
                        output_df.at[index, COL_TAGS] = new_tags
                        output_df.at[index, COL_CHANGE_LOG] = f"MK UP: {current_price}->{target_price} ({reason})"
                        
                    stats['updated_price'] += 1
                else:
                    output_df.at[index, COL_CHANGE_LOG] = "OK"
                
                # SAFETY CHECK
                check_price = output_df.at[index, COL_PRICE]
                check_compare = clean_currency(output_df.at[index, COL_COMPARE])
                
                if check_compare > 0 and check_price >= check_compare:
                    output_df.at[index, COL_COMPARE] = ""
                    current_tags_final = output_df.at[index, COL_TAGS]
                    output_df.at[index, COL_TAGS] = remove_sale_tag(current_tags_final)
                    
            else:
                stats['skipped'] += 1
                
        except Exception as e:
            stats['errors'] += 1
            logs.append(f"Errore Markup Riga {index}: {e}")
            
    return output_df, stats, logs
