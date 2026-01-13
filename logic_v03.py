"""
logic_v03.py - Inventory Sync con Gestione Dinamica Costi e Prezzi
Versione aggiornata per supportare Products_all.csv (12 colonne)

Funzionalità:
1. Mantiene la struttura esatta del file Shopify di input (12 colonne).
2. Aggiornamento COSTI:
   - BBR: Confronta 'Variant Cost' con 'CostoBBRModels' dal file fornitore. Aggiorna se diverso.
   - MCWS: Confronta 'Variant Cost' con 'Net Price' dal file fornitore. Aggiorna se diverso.
3. Aggiornamento PREZZI:
   - Ricalcola 'Variant Price' basandosi sul NUOVO costo e sul Markup (da Vroomi_Markup.txt).
4. Aggiornamento QUANTITÀ:
   - Sincronizza lo stock come nelle versioni precedenti.
"""

import pandas as pd
import numpy as np
import re
from io import StringIO

# ==========================================\n# CONFIGURAZIONE COSTANTI
# ==========================================\n
COL_SKU = 'Variant SKU'
COL_QTY = 'Variant Inventory Qty'
COL_COST = 'Variant Cost'
COL_PRICE = 'Variant Price'
COL_TAGS = 'Tags'

# Colonne Fornitori (Mapping interno)
COL_BBR_SKU = 'DescrizioneVariante'
COL_BBR_COST = 'CostoBBRModels'
COL_BBR_QTY = 'QtaResidua'

COL_MCWS_CODE = 'Code'
COL_MCWS_NET = 'Net Price'
COL_MCWS_BRAND = 'Trademark'
COL_MCWS_EAN = 'EAN'

# ==========================================\n# FUNZIONI DI UTILITÀ
# ==========================================\n
def clean_currency(value):
    """Converte stringhe valuta (es. '19,90') in float."""
    if pd.isna(value) or value == '':
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    
    # Rimuovi simboli valuta e spazi
    val_str = str(value).replace('€', '').replace('$', '').strip()
    # Gestione formati europei vs usa
    if ',' in val_str and '.' in val_str:
        val_str = val_str.replace('.', '').replace(',', '.')
    elif ',' in val_str:
        val_str = val_str.replace(',', '.')
        
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def load_markup_rules(markup_file_content):
    """Carica le regole di markup dal file TXT."""
    markup_dict = {}
    try:
        # Se è un file caricato (BytesIO/StringIO) o una stringa
        if hasattr(markup_file_content, 'read'):
            markup_file_content.seek(0)
            df = pd.read_csv(markup_file_content, sep='\t')
        else:
            # Se è già un dataframe o altro
            return {}

        # Pulisci e normalizza
        if 'TRADEMARK' in df.columns and 'Markup %' in df.columns:
            for _, row in df.iterrows():
                brand = str(row['TRADEMARK']).strip().upper()
                markup_str = str(row['Markup %']).replace(',', '.')
                try:
                    markup_val = float(markup_str)
                    markup_dict[brand] = markup_val
                except:
                    continue
    except Exception as e:
        print(f"Errore caricamento markup: {e}")
        # Fallback di sicurezza
        markup_dict['BBR'] = 1.75
        
    return markup_dict

def get_markup_for_brand(tags, brand_name, markup_dict):
    """
    Trova il markup corretto basandosi sui Tag di Shopify o sul Brand del fornitore.
    """
    # 1. Cerca match esatto nel dizionario (dal file fornitore)
    if brand_name and str(brand_name).upper() in markup_dict:
        return markup_dict[str(brand_name).upper()]
    
    # 2. Cerca match nei TAG di Shopify
    if pd.notna(tags):
        tags_list = [t.strip().upper() for t in str(tags).split(',')]
        for tag in tags_list:
            # Rimuovi prefissi comuni se esistono (es. "brand_ferrari" -> "FERRARI")
            clean_tag = tag.replace('BRAND_', '')
            if clean_tag in markup_dict:
                return markup_dict[clean_tag]
            if tag in markup_dict:
                return markup_dict[tag]
    
    # 3. Default generico se non trovato
    return 1.50

# ==========================================\n# LOGICA PRINCIPALE (V03)
# ==========================================\n
def process_inventory_v03(df_shopify, df_mcws, df_bbr, markup_file):
    """
    Elabora l'inventario confrontando Shopify con BBR e MCWS.
    Aggiorna Qta, Costi e Prezzi.
    """
    
    # --- 1. PREPARAZIONE DATI ---
    
    # Carica Markup
    markup_rules = load_markup_rules(markup_file)
    
    # Dizionari per accesso rapido ai dati fornitori
    # BBR Lookup: SKU -> {Cost, Qty}
    bbr_lookup = {}
    if not df_bbr.empty:
        # Assicuriamoci che i nomi colonne siano corretti (rimuovi spazi extra)
        df_bbr.columns = [c.strip() for c in df_bbr.columns]
        for _, row in df_bbr.iterrows():
            sku = str(row.get(COL_BBR_SKU, '')).strip()
            if sku:
                bbr_lookup[sku] = {
                    'cost': clean_currency(row.get(COL_BBR_COST, 0)),
                    'qty': int(pd.to_numeric(row.get(COL_BBR_QTY, 0), errors='coerce') or 0)
                }

    # MCWS Lookup: Code -> {Cost, Qty, Brand}
    # Creiamo due indici: uno per Code esatto, uno per EAN se serve
    mcws_lookup = {}
    if not df_mcws.empty:
        df_mcws.columns = [c.strip().replace('"', '') for c in df_mcws.columns]
        for _, row in df_mcws.iterrows():
            code = str(row.get(COL_MCWS_CODE, '')).strip()
            if code:
                mcws_lookup[code] = {
                    'cost': clean_currency(row.get(COL_MCWS_NET, 0)),
                    'qty': 999, # MCWS stocklist implica disponibilità, oppure logica specifica
                    'brand': str(row.get(COL_MCWS_BRAND, ''))
                }
    
    # Statistiche e Log
    stats = {'processed': 0, 'updated_qty': 0, 'updated_cost': 0, 'updated_price': 0, 'errors': 0}
    logs = []
    
    # --- 2. ELABORAZIONE SHOPIFY ---
    
    # Creiamo una copia per non modificare l'originale durante l'iterazione
    # Manteniamo ESATTAMENTE le colonne originali
    output_df = df_shopify.copy()
    
    # Aggiungi colonna Change Log se non esiste (utile per debug, poi si può rimuovere se necessario)
    if 'Change Log' not in output_df.columns:
        output_df['Change Log'] = ''
        
    for index, row in output_df.iterrows():
        try:
            stats['processed'] += 1
            sku = str(row.get(COL_SKU, '')).strip()
            tags = str(row.get(COL_TAGS, ''))
            
            # Valori attuali
            current_qty = int(pd.to_numeric(row.get(COL_QTY, 0), errors='coerce') or 0)
            current_cost = clean_currency(row.get(COL_COST, 0))
            current_price = clean_currency(row.get(COL_PRICE, 0))
            
            new_qty = current_qty
            new_cost = current_cost
            new_price = current_price
            
            changes = []
            found_supplier = False
            supplier_brand = ""
            
            # --- LOGICA IDENTIFICAZIONE FORNITORE E DATI ---
            
            # 1. CHECK BBR
            # BBR si identifica spesso se lo SKU è nel file BBR
            if sku in bbr_lookup:
                found_supplier = True
                supplier_data = bbr_lookup[sku]
                
                # A) Aggiorna COSTO (Logica Richiesta)
                # "compara il valore della colonna CostoBBRModels con Variant Cost"
                supplier_cost = supplier_data['cost']
                if supplier_cost > 0 and abs(supplier_cost - current_cost) > 0.01:
                    new_cost = supplier_cost
                    changes.append(f"COST(BBR): {current_cost:.2f}->{new_cost:.2f}")
                    stats['updated_cost'] += 1
                
                # B) Aggiorna QTA
                supplier_qty = supplier_data['qty']
                # Logica BBR: se < 3 diventa 0 (esempio da versioni precedenti) o diretta
                # Usiamo diretta per ora salvo logica specifica
                if supplier_qty != current_qty:
                    new_qty = supplier_qty
                    changes.append(f"QTY(BBR): {current_qty}->{new_qty}")
                    stats['updated_qty'] += 1
                    
                supplier_brand = "BBR"

            # 2. CHECK MCWS
            # Se non trovato in BBR, cerca in MCWS
            elif not found_supplier:
                # MCWS spesso richiede mapping SKU -> Code.
                # Assumiamo qui che SKU Shopify corrisponda a Code MCWS o debba essere pulito
                # Esempio: "W18030009" (Shopify) -> "W18030009" (MCWS)
                # In logic_v02 c'era logica complessa, qui usiamo match diretto per la richiesta "Dinamica"
                
                match_obj = None
                if sku in mcws_lookup:
                    match_obj = mcws_lookup[sku]
                
                if match_obj:
                    found_supplier = True
                    # A) Aggiorna COSTO (Logica Richiesta)
                    # "compara Net Price con Variant Cost"
                    supplier_cost = match_obj['cost']
                    if supplier_cost > 0 and abs(supplier_cost - current_cost) > 0.01:
                        new_cost = supplier_cost
                        changes.append(f"COST(MCWS): {current_cost:.2f}->{new_cost:.2f}")
                        stats['updated_cost'] += 1
                    
                    # B) Aggiorna QTA (MCWS stocklist contiene solo disponibili)
                    if current_qty == 0:
                        new_qty = 1 # Riattiva se presente nel file
                        changes.append(f"QTY(MCWS): 0->1")
                        stats['updated_qty'] += 1
                    
                    supplier_brand = match_obj['brand']

            # --- 3. AGGIORNAMENTO PREZZI (MARKUP) ---
            # Se il costo è cambiato, o se vogliamo forzare il ricalcolo
            if abs(new_cost - current_cost) > 0.01:
                # Determina il Markup
                if found_supplier:
                    markup = get_markup_for_brand(tags, supplier_brand, markup_rules)
                else:
                    markup = 1.5 # Default safety
                
                calculated_price = round(new_cost * markup, 2)
                
                # Applica solo se diverso
                if abs(calculated_price - current_price) > 0.01:
                    new_price = calculated_price
                    changes.append(f"PRICE: {current_price:.2f}->{new_price:.2f}")
                    stats['updated_price'] += 1

            # --- 4. SALVATAGGIO MODIFICHE ---
            output_df.at[index, COL_QTY] = new_qty
            output_df.at[index, COL_COST] = new_cost
            output_df.at[index, COL_PRICE] = new_price
            
            if changes:
                output_df.at[index, 'Change Log'] = " | ".join(changes)
                # logs.append(f"{sku}: {', '.join(changes)}")

        except Exception as e:
            stats['errors'] += 1
            logs.append(f"Errore riga {index} (SKU {row.get(COL_SKU, 'NA')}): {str(e)}")

    return output_df, stats, [], logs