"""
logic_v02.py - Inventory Sync con Gestione Costi e Prezzi

Logica avanzata per sincronizzare l'inventario Shopify con i listini fornitori,
con aggiornamento automatico di costi e prezzi basato su regole configurabili.

Funzionalità:
1. Comparazione inventory (come logic.py originale)
2. Gestione COSTI:
   - BBR: aggiorna "Variant Cost" se diverso da "CostoBBRModels"
   - MCWS: aggiorna "Variant Cost" se diverso da "Net Price"
3. Gestione PREZZI:
   - BBR: calcola "Variant Price" = "Variant Cost" * 1.75
   - MCWS: calcola "Variant Price" = "Variant Cost" * markup_brand (da tabella)

Output: File CSV con 12 colonne, struttura identica a Products.csv
"""

import pandas as pd
import re
from collections import defaultdict
from typing import Tuple, Dict, List, Optional

# ==========================================
# CONFIGURAZIONE
# ==========================================

# --- COLONNE ATTESE NEI FILE ---
# Shopify (Target) - formato Products.csv con 12 colonne
COL_SHOPIFY_SKU = 'Variant SKU'
COL_SHOPIFY_QTY = 'Variant Inventory Qty'
COL_SHOPIFY_COST = 'Variant Cost'
COL_SHOPIFY_PRICE = 'Variant Price'
COL_SHOPIFY_TAGS = 'Tags'

# Colonne per costi e identificazione fonte
COL_COSTO_BBR = 'CostoBBRModels'  # Costo da listino BBR
COL_NET_PRICE = 'Net Price'       # Costo da listino MCWS
COL_BRAND = 'Brand'               # Brand estratto dai Tags

# MCWS (Source A)
COL_MCWS_OUR_CODE = 'Our Code'
COL_MCWS_CODE = 'Code'
COL_MCWS_TRADEMARK = 'Trademark'

# BBR (Source B)
COL_BBR_SKU = 'DescrizioneVariante'
COL_BBR_QTY = 'QtaResidua'

# --- TRADEMARK FILTER ---
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

# --- MARKUP CONFIGURAZIONE ---
BBR_MARKUP = 1.75  # Markup fisso per prodotti BBR

# Tabella markup per brand MCWS (caricata da Vroomi_Markup.txt)
MCWS_MARKUP_TABLE: Dict[str, float] = {}

# ==========================================
# DEBUG / CHANGE LOG CONFIG
# ==========================================

# Imposta a True per abilitare la colonna con il log delle variazioni
# Imposta a False per disabilitarla (una volta verificato il funzionamento)
ENABLE_CHANGE_LOG = True

COL_CHANGE_LOG = 'Change Log'  # Nome della colonna per il log

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


def clean_numeric(value, default=0.0):
    """Converte un valore in numero float, gestendo formati europei (virgola)"""
    if pd.isna(value) or value == '':
        return default
    try:
        # Sostituisci virgola con punto per formati europei
        return float(str(value).replace(',', '.').replace(' ', ''))
    except (ValueError, TypeError):
        return default


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


def load_markup_table(file_path: str = 'Vroomi_Markup.txt') -> Dict[str, float]:
    """
    Carica la tabella markup da file Vroomi_Markup.txt.
    
    Formato atteso:
    TRADEMARK    Markup %
    Alerte       1,50
    Autoart      1,50
    ...
    
    Returns:
        Dict con lowercase trademark -> markup float
    """
    global MCWS_MARKUP_TABLE
    
    try:
        df = pd.read_csv(file_path, sep='\t', dtype=str)
        
        for _, row in df.iterrows():
            trademark = clean_trademark(row.iloc[0])  # Prima colonna
            markup_str = row.iloc[1]  # Seconda colonna
            
            if trademark and markup_str:
                markup = clean_numeric(markup_str)
                MCWS_MARKUP_TABLE[trademark] = markup
        
        return MCWS_MARKUP_TABLE
    
    except Exception as e:
        print(f"Errore caricamento tabella markup: {e}")
        return {}


def extract_brand_from_tags(tags: str) -> str:
    """
    Estrae il brand dai tags Shopify.
    Cerca pattern come "brand_nome" nei tags.
    
    Args:
        tags: Stringa contenente i tags (es. "1/43, brand_ferrari, F1, FERRARI")
    
    Returns:
        Brand in uppercase (es. "FERRARI") o stringa vuota se non trovato
    """
    if pd.isna(tags) or tags == '':
        return ""
    
    tags_lower = str(tags).lower()
    
    # Cerca pattern "brand_X" dove X è il nome del brand
    brand_match = re.search(r'brand_([a-z0-9\-]+)', tags_lower)
    if brand_match:
        brand_name = brand_match.group(1)
        # Converti in uppercase e sostituisci - con spazio per matching
        return brand_name.upper().replace('-', ' ')
    
    # Se non trova pattern brand_, prova a cercare tra i trademark validi
    for trademark in VALID_TRADEMARKS:
        trademark_lower = trademark.lower().replace('-', ' ')
        if trademark_lower in tags_lower:
            return trademark
    
    return ""


def identify_product_source(row: pd.Series) -> str:
    """
    Identifica se un prodotto proviene da BBR o MCWS basandosi sui dati disponibili.
    
    Args:
        row: Riga del DataFrame Shopify
    
    Returns:
        'BBR', 'MCWS' o 'UNKNOWN'
    """
    # Se abbiamo un costo BBR valido, è un prodotto BBR
    costo_bbr = clean_numeric(row.get(COL_COSTO_BBR, None))
    if costo_bbr > 0:
        return 'BBR'
    
    # Se abbiamo un net price valido, è un prodotto MCWS
    net_price = clean_numeric(row.get(COL_NET_PRICE, None))
    if net_price > 0:
        return 'MCWS'
    
    # Se abbiamo Variant Cost, prova a determinare la fonte dal brand
    variant_cost = clean_numeric(row.get(COL_SHOPIFY_COST, None))
    if variant_cost <= 0:
        return 'UNKNOWN'
    
    # Prova a determinare dal brand
    brand = extract_brand_from_tags(row.get(COL_SHOPIFY_TAGS, ''))
    
    # Se è un brand BBR, usa logica BBR
    if 'BBR' in brand or 'BBR-MODELS' in brand:
        return 'BBR'
    
    return 'MCWS'  # Default fallback


def identify_product_source(row: pd.Series) -> str:
    """
    Identifica se un prodotto proviene da BBR o MCWS basandosi sui dati disponibili.
    
    Args:
        row: Riga del DataFrame Shopify
    
    Returns:
        'BBR', 'MCWS' o 'UNKNOWN'
    """
    # Se abbiamo un costo BBR valido, è un prodotto BBR
    costo_bbr = clean_numeric(row.get(COL_COSTO_BBR, None))
    if costo_bbr > 0:
        return 'BBR'
    
    # Se abbiamo un net price valido, è un prodotto MCWS
    net_price = clean_numeric(row.get(COL_NET_PRICE, None))
    if net_price > 0:
        return 'MCWS'
    
    # Se abbiamo Variant Cost, prova a determinare la fonte dal brand
    variant_cost = clean_numeric(row.get(COL_SHOPIFY_COST, None))
    if variant_cost <= 0:
        return 'UNKNOWN'
    
    # Prova a determinare dal brand
    brand = extract_brand_from_tags(row.get(COL_SHOPIFY_TAGS, ''))
    
    # Se è un brand BBR, usa logica BBR
    if 'BBR' in brand or 'BBR-MODELS' in brand:
        return 'BBR'
    
    return 'MCWS'  # Default fallback


def add_change_log_column(
    df_output: pd.DataFrame,
    original_df: pd.DataFrame,
    log_messages: List[str]
) -> pd.DataFrame:
    """
    Aggiunge una colonna 'Change Log' che descrive tutte le variazioni trovate.
    
    Questa funzione è pensata per il DEBUG e la VERIFICA.
    Una volta verificato che tutto funziona correttamente,
    può essere disabilitata impostando ENABLE_CHANGE_LOG = False in cima al file.
    
    Variazioni tracciate:
    - Inventory: qty changed (0→1 o 1→0)
    - Cost BBR: costo variato rispetto a CostoBBRModels
    - Cost MCWS: costo variato rispetto a Net Price
    - Price BBR: prezzo ricalcolato con markup 1.75
    - Price MCWS: prezzo ricalcolato con markup brand
    
    Args:
        df_output: DataFrame processato con i nuovi valori
        original_df: DataFrame originale di Shopify per confronto
        log_messages: Lista per accumulare messaggi di log
    
    Returns:
        DataFrame con colonna 'Change Log' aggiunta
    """
    if not ENABLE_CHANGE_LOG:
        log_messages.append("   [CHANGE LOG] Disabilitato (ENABLE_CHANGE_LOG = False)")
        return df_output
    
    if df_output.empty:
        log_messages.append("   [CHANGE LOG] DataFrame vuoto, nessuna elaborazione")
        return df_output
    
    log_messages.append("   [CHANGE LOG] Inizio analisi variazioni...")
    
    # Crea un dizionario SKU -> riga originale per lookup veloce
    original_by_sku = {}
    for idx, row in original_df.iterrows():
        sku = clean_code(row.get(COL_SHOPIFY_SKU, ''))
        if sku:
            original_by_sku[sku] = row
    
    # Aggiungi la colonna Change Log
    df_output[COL_CHANGE_LOG] = ''
    
    change_count = 0
    
    for idx, row in df_output.iterrows():
        sku = clean_code(row.get(COL_SHOPIFY_SKU, ''))
        changes = []
        
        # Get original row for comparison
        original_row = original_by_sku.get(sku, pd.Series())
        
        if original_row.empty:
            # Prodotto non trovato nell'originale, skip
            df_output.at[idx, COL_CHANGE_LOG] = 'NUOVO PRODOTTO'
            change_count += 1
            continue
        
        # ========================================
        # 1. CHECK INVENTORY CHANGES
        # ========================================
        original_qty = clean_numeric(original_row.get(COL_SHOPIFY_QTY, 0))
        new_qty = clean_numeric(row.get(COL_SHOPIFY_QTY, 0))
        
        if original_qty != new_qty:
            if new_qty == 1:
                changes.append(f"QTY: {int(original_qty)}→{int(new_qty)} (RIATTIVATO)")
            elif new_qty == 0:
                changes.append(f"QTY: {int(original_qty)}→{int(new_qty)} (DISATTIVATO)")
            else:
                changes.append(f"QTY: {int(original_qty)}→{int(new_qty)}")
        
        # ========================================
        # 2. CHECK COST CHANGES
        # ========================================
        original_cost = clean_numeric(original_row.get(COL_SHOPIFY_COST, 0))
        new_cost = clean_numeric(row.get(COL_SHOPIFY_COST, 0))
        source = identify_product_source(row)
        
        if source == 'BBR':
            costo_bbr = clean_numeric(row.get(COL_COSTO_BBR, 0))
            if costo_bbr > 0 and new_cost != original_cost:
                changes.append(f"COST BBR: {original_cost:.2f}→{new_cost:.2f} (da CostoBBRModels={costo_bbr:.2f})")
        elif source == 'MCWS':
            net_price = clean_numeric(row.get(COL_NET_PRICE, 0))
            if net_price > 0 and new_cost != original_cost:
                changes.append(f"COST MCWS: {original_cost:.2f}→{new_cost:.2f} (da NetPrice={net_price:.2f})")
        
        # ========================================
        # CHECK PRICE CHANGES (solo per log, non per filtro)
        # ========================================
        price_changes = []
        original_price = clean_numeric(original_row.get(COL_SHOPIFY_PRICE, 0))
        new_price = clean_numeric(row.get(COL_SHOPIFY_PRICE, 0))
        
        if source == 'BBR':
            expected_price = round(new_cost * BBR_MARKUP, 2) if new_cost > 0 else 0
            if original_price != expected_price and new_price == expected_price:
                price_changes.append(f"PRICE BBR: {original_price:.2f}→{new_price:.2f} (markup={BBR_MARKUP})")
        elif source == 'MCWS':
            brand = extract_brand_from_tags(row.get(COL_SHOPIFY_TAGS, ''))
            brand_lookup = brand.upper().replace(' ', '-')
            if brand_lookup in MCWS_MARKUP_TABLE:
                markup = MCWS_MARKUP_TABLE[brand_lookup]
                expected_price = round(new_cost * markup, 2) if new_cost > 0 else 0
                if original_price != expected_price and new_price == expected_price:
                    price_changes.append(f"PRICE MCWS: {original_price:.2f}→{new_price:.2f} (markup={markup}, brand={brand})")
        
        # ========================================
        # SCRIVI IL LOG
        # ========================================
        # Combina tutti i cambiamenti
        all_changes = changes + price_changes
        
        if all_changes:
            df_output.at[idx, COL_CHANGE_LOG] = ' | '.join(all_changes)
        
        # FILTRO: Considera solo QTY e COST per determinare se includere la riga
        # (I prezzi sono calcolati automaticamente dai costi, quindi non sono "modifiche" da verificare)
        has_qty_or_cost_change = len(changes) > 0
        
        if has_qty_or_cost_change:
            change_count += 1
        else:
            # Se non ci sono variazioni di qty o cost, marca come vuoto
            df_output.at[idx, COL_CHANGE_LOG] = ''
    
    log_messages.append(f"   [CHANGE LOG] Trovate {change_count} righe con variazioni (QTY o COST)")
    
    # FILTRO: Mantieni solo le righe con variazioni di QTY o COST
    df_filtered = df_output[df_output[COL_CHANGE_LOG] != ''].copy()
    
    log_messages.append(f"   [CHANGE LOG] Output filtrato: {len(df_filtered)} righe con modifiche")
    
    return df_filtered


def process_costs_and_prices(
    df_output: pd.DataFrame,
    log_messages: List[str]
) -> Tuple[pd.DataFrame, Dict]:
    """
    Processa costi e prezzi per tutti i prodotti nel DataFrame.
    
    Logica:
    1. COSTI:
       - BBR: confronta CostoBBRModels con Variant Cost, aggiorna se diverso
       - MCWS: confronta Net Price con Variant Cost, aggiorna se diverso
    
    2. PREZZI:
       - BBR: Variant Price = Variant Cost * 1.75
       - MCWS: Variant Price = Variant Cost * markup_brand
    
    Args:
        df_output: DataFrame con i prodotti da processare
        log_messages: Lista per accumulare messaggi di log
    
    Returns:
        Tuple: (DataFrame processato, statistiche)
    """
    stats = {
        'cost_updates_bbr': 0,
        'cost_updates_mcws': 0,
        'price_updates_bbr': 0,
        'price_updates_mcws': 0,
        'total_bbr': 0,
        'total_mcws': 0,
        'total_unknown': 0,
        'missing_markup_brands': set()
    }
    
    if df_output.empty:
        log_messages.append("   [COSTI/PREZZI] DataFrame vuoto, nessuna elaborazione")
        return df_output, stats
    
    # Assicuriamoci che le colonne necessarie esistano
    # Se non esistono, le creiamo
    if COL_COSTO_BBR not in df_output.columns:
        df_output[COL_COSTO_BBR] = None
    if COL_NET_PRICE not in df_output.columns:
        df_output[COL_NET_PRICE] = None
    
    log_messages.append("   [COSTI/PREZZI] Inizio elaborazione costi e prezzi...")
    
    # Carica tabella markup se non ancora caricata
    if not MCWS_MARKUP_TABLE:
        load_markup_table()
        log_messages.append(f"   [COSTI/PREZZI] Tabella markup caricata: {len(MCWS_MARKUP_TABLE)} brand")
    
    for idx, row in df_output.iterrows():
        source = identify_product_source(row)
        
        # Aggiorna statistiche per fonte
        if source == 'BBR':
            stats['total_bbr'] += 1
        elif source == 'MCWS':
            stats['total_mcws'] += 1
        else:
            stats['total_unknown'] += 1
            continue  # Skip prodotti non identificati
        
        # Inizializza variabili
        current_cost = clean_numeric(row.get(COL_SHOPIFY_COST, 0))
        new_cost = current_cost
        new_price = clean_numeric(row.get(COL_SHOPIFY_PRICE, 0))
        
        # ========================================
        # A) GESTIONE COSTI
        # ========================================
        
        if source == 'BBR':
            # BBR: confronta CostoBBRModels con Variant Cost
            costo_bbr = clean_numeric(row.get(COL_COSTO_BBR, 0))
            if costo_bbr > 0 and current_cost != costo_bbr:
                new_cost = costo_bbr
                df_output.at[idx, COL_SHOPIFY_COST] = new_cost
                stats['cost_updates_bbr'] += 1
        
        elif source == 'MCWS':
            # MCWS: confronta Net Price con Variant Cost
            net_price = clean_numeric(row.get(COL_NET_PRICE, 0))
            if net_price > 0 and current_cost != net_price:
                new_cost = net_price
                df_output.at[idx, COL_SHOPIFY_COST] = new_cost
                stats['cost_updates_mcws'] += 1
        
        # ========================================
        # B) GESTIONE PREZZI
        # ========================================
        
        if source == 'BBR':
            # BBR: Variant Price = Variant Cost * 1.75
            expected_price = round(new_cost * BBR_MARKUP, 2)
            if new_price != expected_price:
                df_output.at[idx, COL_SHOPIFY_PRICE] = expected_price
                stats['price_updates_bbr'] += 1
        
        elif source == 'MCWS':
            # MCWS: identifica brand e applica markup
            brand = extract_brand_from_tags(row.get(COL_SHOPIFY_TAGS, ''))
            
            # Normalizza brand per lookup (uppercase, spazi -> underscore)
            brand_lookup = brand.upper().replace(' ', '-')
            if brand_lookup in MCWS_MARKUP_TABLE:
                markup = MCWS_MARKUP_TABLE[brand_lookup]
                expected_price = round(new_cost * markup, 2)
                
                if new_price != expected_price:
                    df_output.at[idx, COL_SHOPIFY_PRICE] = expected_price
                    stats['price_updates_mcws'] += 1
            else:
                # Brand non trovato nella tabella markup
                if brand and brand not in stats['missing_markup_brands']:
                    stats['missing_markup_brands'].add(brand)
    
    # Log dei risultati
    log_messages.append(f"   [COSTI/PREZZI] Prodotti BBR: {stats['total_bbr']} (costi aggiornati: {stats['cost_updates_bbr']}, prezzi aggiornati: {stats['price_updates_bbr']})")
    log_messages.append(f"   [COSTI/PREZZI] Prodotti MCWS: {stats['total_mcws']} (costi aggiornati: {stats['cost_updates_mcws']}, prezzi aggiornati: {stats['price_updates_mcws']})")
    
    if stats['missing_markup_brands']:
        log_messages.append(f"   [COSTI/PREZZI] Brand senza markup configurato: {', '.join(sorted(stats['missing_markup_brands']))}")
    
    return df_output, stats


def process_inventory_v02(
    products_df: pd.DataFrame,
    markup_file: str = 'Vroomi_Markup.txt'
) -> Tuple[pd.DataFrame, Dict]:
    """
    Processa il file unificato Products.csv (12 colonne) e genera il report di aggiornamento.
    
    Questa versione lavora con un singolo file unificato contenente tutte le informazioni:
    - Dati Shopify: SKU, Variant SKU, Qty, Cost, Price, Tags
    - Dati BBR: CostoBBRModels
    - Dati MCWS: Net Price, Trademark, Brand, Code, QTY
    
    Args:
        products_df: DataFrame del file Products.csv (12 colonne)
        markup_file: Percorso file tabella markup MCWS
    
    Returns:
        Tuple: (df_output, stats_dict)
            - df_output: DataFrame con solo le righe con variazioni di QTY o COSTO
            - stats_dict: Dizionario con statistiche
    """
    global MCWS_MARKUP_TABLE
    
    log_messages = []
    stats = {
        'total_rows': 0,
        'qty_changes': 0,
        'cost_changes': 0,
        'cost_updates_bbr': 0,
        'cost_updates_mcws': 0,
        'price_updates_bbr': 0,
        'price_updates_mcws': 0,
        'total_bbr': 0,
        'total_mcws': 0,
        'missing_markup_brands': set()
    }
    
    log_messages.append("=" * 50)
    log_messages.append("INVENTORY SYNC V02 - FORMATO UNIFICATO")
    log_messages.append("=" * 50)
    
    # ==========================================
    # 0. VALIDAZIONE COLONNE
    # ==========================================
    required_cols = [
        COL_SHOPIFY_SKU, COL_SHOPIFY_QTY, COL_SHOPIFY_COST,
        COL_COSTO_BBR, COL_NET_PRICE
    ]
    
    missing_cols = [c for c in required_cols if c not in products_df.columns]
    if missing_cols:
        log_messages.append(f"ERRORE: Colonne mancanti: {missing_cols}")
        return pd.DataFrame(), stats
    
    # ==========================================
    # 1. CARICA TABELLA MARKUP
    # ==========================================
    log_messages.append("0. Caricamento tabella markup MCWS...")
    load_markup_table(markup_file)
    log_messages.append(f"   Caricati {len(MCWS_MARKUP_TABLE)} brand dalla tabella markup")
    
    # ==========================================
    # 2. ELABORAZIONE DATI - COSTI E PREZZI
    # ==========================================
    log_messages.append("1. Processing Costi e Prezzi...")
    df_output, cost_price_stats = process_costs_and_prices(products_df.copy(), log_messages)
    
    # Merge delle statistiche
    stats.update({
        'cost_updates_bbr': cost_price_stats.get('cost_updates_bbr', 0),
        'cost_updates_mcws': cost_price_stats.get('cost_updates_mcws', 0),
        'price_updates_bbr': cost_price_stats.get('price_updates_bbr', 0),
        'price_updates_mcws': cost_price_stats.get('price_updates_mcws', 0),
        'total_bbr': cost_price_stats.get('total_bbr', 0),
        'total_mcws': cost_price_stats.get('total_mcws', 0),
        'missing_markup_brands': cost_price_stats.get('missing_markup_brands', set())
    })
    
    # ==========================================
    # 3. CONFRONTO QUANTITÀ
    # ==========================================
    log_messages.append("2. Confronto Quantità...")
    
    if COL_SHOPIFY_QTY not in df_output.columns:
        log_messages.append(f"ERRORE: Colonna '{COL_SHOPIFY_QTY}' mancante")
        return pd.DataFrame(), stats
    
    # Aggiungi colonna per tracking modifiche
    df_output['change_count'] = 0
    df_output['qty_changed'] = False
    df_output['cost_changed'] = False
    
    for idx, row in df_output.iterrows():
        stats['total_rows'] += 1
        
        # Confronto quantità
        try:
            shopify_qty = float(str(row.get(COL_SHOPIFY_QTY, 0)).replace(',', '.'))
        except:
            shopify_qty = 0
        
        try:
            source_qty = float(str(row.get('QTY', 0)).replace(',', '.'))
        except:
            source_qty = 0
        
        if shopify_qty != source_qty:
            df_output.at[idx, COL_SHOPIFY_QTY] = source_qty
            df_output.at[idx, 'qty_changed'] = True
            stats['qty_changes'] += 1
            df_output.at[idx, 'change_count'] = df_output.at[idx, 'change_count'] + 1
    
    # ==========================================
    # 4. FILTRO VARIAZIONI (QTY o COSTO)
    # ==========================================
    # Filtra per mantenere solo righe con variazioni di QTY o COSTO
    df_filtered = df_output[df_output['change_count'] > 0].copy()
    
    # Rimuovi colonne temporanee
    cols_to_drop = ['change_count', 'qty_changed', 'cost_changed']
    df_filtered = df_filtered.drop(columns=[c for c in cols_to_drop if c in df_filtered.columns])
    
    log_messages.append(f"3. Righe finali con variazioni: {len(df_filtered)}")
    log_messages.append(f"   - Variazioni QTY: {stats['qty_changes']}")
    log_messages.append(f"   - Variazioni COSTO: {stats['cost_updates_bbr'] + stats['cost_updates_mcws']}")
    
    return df_filtered, stats
        
        if not sku_clean:
            stats['total_rows'] += 1
        else:
            # Aggiungi anche le righe senza modifiche all'inventario
            # per poter elaborare costi e prezzi
            pass
    
    # ==========================================
    # 3. FILTRO VARIAZIONI (QTY o COSTO)
    # ==========================================
    # Filtra per mantenere solo righe con variazioni di QTY o COSTO
    if 'change_count' in df_output.columns:
        df_output = df_output[df_output['change_count'] > 0].copy()
        df_output = df_output.drop(columns=['change_count'])
    
    log_messages.append(f"4. Righe finali con variazioni: {len(df_output)}")
    
    return df_output, stats


# ==========================================
# FUNZIONE DI BACKWARD COMPATIBILITY
# ==========================================

def process_inventory(shopify_df, mcws_df, bbr_df):
    """
    Funzione wrapper per compatibilità con versione precedente.
    """
    global MCWS_MARKUP_TABLE
    
    log_messages = []
    duplicate_report = []
    all_stats = {
        'inventory': {'total': 0, 'updates_1': 0, 'updates_0': 0},
        'costs_prices': {}
    }
    rows_output = []
    processed_skus = set()
    
    log_messages.append("=" * 50)
    log_messages.append("INVENTORY SYNC V02 - BACKWARD COMPATIBILITY")
    log_messages.append("=" * 50)
    
    # Load markup table
    load_markup_table('Vroomi_Markup.txt')
    
    # Process MCWS
    log_messages.append("1. Processing MCWS...")
    available_skus = set()
    
    # Process MCWS codes (simplified)
    for idx, row in mcws_df.iterrows():
        code = str(row.get(COL_MCWS_CODE, ''))
        c = clean_code(code)
        if c:
            available_skus.add(c)
    
    # Process BBR
    log_messages.append("2. Processing BBR...")
    for idx, row in bbr_df.iterrows():
        code = str(row.get(COL_BBR_SKU, ''))
        c = clean_code(code)
        if c:
            available_skus.add(c)
    
    # Compare with Shopify
    log_messages.append("3. Comparing with Shopify...")
    for idx, row in shopify_df.iterrows():
        all_stats['inventory']['total'] += 1
        raw_sku = str(row.get(COL_SHOPIFY_SKU, ''))
        sku_clean = clean_code(raw_sku)
        
        if not sku_clean or sku_clean in processed_skus:
            continue
        processed_skus.add(sku_clean)
        
        try:
            current_val = float(row.get(COL_SHOPIFY_QTY, 0))
        except:
            current_val = 0
        
        current_logic = 1 if current_val > 0 else 0
        is_in_stock = sku_clean in available_skus
        new_qty = None
        
        if is_in_stock and current_logic == 0:
            new_qty = 1
            all_stats['inventory']['updates_1'] += 1
        elif not is_in_stock and current_logic == 1:
            new_qty = 0
            all_stats['inventory']['updates_0'] += 1
        
        if new_qty is not None:
            out_row = row.copy()
            out_row[COL_SHOPIFY_QTY] = new_qty
            rows_output.append(out_row)
    
    df_output = pd.DataFrame(rows_output) if rows_output else pd.DataFrame()
    
    # Process costs and prices
    if not df_output.empty:
        log_messages.append("4. Processing Costs and Prices...")
        df_output, cost_price_stats = process_costs_and_prices(df_output, log_messages)
        all_stats['costs_prices'] = cost_price_stats
    
    return df_output, all_stats, duplicate_report, log_messages


# ==========================================
# FUNZIONE DI BACKWARD COMPATIBILITY
# ==========================================

def process_inventory(shopify_df, mcws_df, bbr_df):
    """
    Funzione wrapper per compatibilità con versione precedente.
    Usa la nuova logica V02.
    """
    result_df, stats, duplicate_report, log_messages = process_inventory_v02(
        shopify_df, mcws_df, bbr_df
    )
    
    # Converte stats nel formato vecchio per compatibilità
    old_stats = {
        'total': stats['inventory']['total'],
        'updates_1': stats['inventory']['updates_1'],
        'updates_0': stats['inventory']['updates_0']
    }
    
    return result_df, old_stats, duplicate_report, log_messages


# ==========================================
# ESECUZIONE DIRETTA (per testing)
# ==========================================

if __name__ == "__main__":
    import sys
    import os
    
    print("=" * 60)
    print("INVENTORY SYNC V02 - GESTIONE COSTI E PREZZI")
    print("=" * 60)
    
    # Percorsi file di default
    base_path = "."
    
    files = {
        'shopify': os.path.join(base_path, "Products.csv"),
        'mcws': os.path.join(base_path, "stocklist.csv"),
        'bbr': os.path.join(base_path, "export_260112_180531.xls"),
        'markup': os.path.join(base_path, "Vroomi_Markup.txt")
    }
    
    # Verifica esistenza file
    missing = [k for k, v in files.items() if not os.path.exists(v)]
    if missing:
        print(f"ATTENZIONE: File non trovati: {missing}")
        print("Verifica i percorsi e riprova.")
        sys.exit(1)
    
    try:
        # Carica file
        print("\nCaricamento file...")
        
        df_shopify = pd.read_csv(files['shopify'], dtype=str)
        print(f"  Shopify: {len(df_shopify)} righe, colonne: {list(df_shopify.columns)}")
        
        df_mcws = pd.read_csv(files['mcws'], dtype=str)
        print(f"  MCWS: {len(df_mcws)} righe")
        
        df_bbr = pd.read_excel(files['bbr'], dtype=str)
        print(f"  BBR: {len(df_bbr)} righe")
        
        # Esegui elaborazione
        print("\nElaborazione in corso...")
        df_output, all_stats, duplicate_report, log_messages = process_inventory_v02(
            df_shopify, df_mcws, df_bbr, files['markup']
        )
        
        # Stampa log
        print("\n" + "=" * 60)
        print("LOG ELABORAZIONE")
        print("=" * 60)
        for msg in log_messages:
            print(msg)
        
        # Salva output
        if not df_output.empty:
            output_file = os.path.join(base_path, "output_v02.csv")
            df_output.to_csv(output_file, index=False)
            print(f"\n✅ Output salvato: {output_file}")
            print(f"   Righe: {len(df_output)}")
            print(f"   Colonne: {list(df_output.columns)}")
        else:
            print("\n⚠️ Nessun output generato")
        
    except Exception as e:
        print(f"\nERRORE: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
