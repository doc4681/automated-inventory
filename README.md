# 📦 Inventory Sync WebApp

Una webapp per sincronizzare l'inventario tra Shopify e i listini fornitori (MCWS e BBR).

## 🚀 Deploy su GitHub e Streamlit Cloud

### Prerequisiti
- Un account [GitHub](https://github.com)
- Un account [Streamlit Community Cloud](https://share.streamlit.io)

### Passaggi per il deployment

#### 1. Crea il repository su GitHub
1. Vai su [github.com](https://github.com) e accedi
2. Clicca su **"New repository"**
3. Assegna un nome (es. `inventory-sync-webapp`)
4. Imposta il repository come **Public**
5. Clicca **"Create repository"**

#### 2. Carica i file
Carica i seguenti file nel repository:
- `app.py` (file principale dell'applicazione)
- `logic.py` (logica di elaborazione)
- `requirements.txt` (dipendenze)

#### 3. Collega a Streamlit Cloud
1. Vai su [share.streamlit.io](https://share.streamlit.io) e accedi con GitHub
2. Clicca su **"New App"**
3. Seleziona il repository appena creato
4. Seleziona il branch (solitamente `main`)
5. Imposta il file principale: `app.py`
6. Clicca **"Deploy"**

#### 4. Accedi alla tua webapp
Dopo pochi minuti, Streamlit genererà un URL pubblico (es. `https://tuo-nome.streamlit.app`) che potrai usare da qualsiasi dispositivo.

---

## 📖 Come usare la webapp

### 1. Prepara i file CSV
Sono supportati due formati di elaborazione:

#### Formato Originale (3 file separati)
| File | Descrizione | Colonne richieste |
|------|-------------|-------------------|
| `Shopify_Products.csv` | Export prodotti Shopify | `Variant SKU`, `Variant Inventory Qty` |
| `MCWS_stocklist.csv` | Listino MCWS | `Our Code`, `Code`, `Trademark` |
| `BBR_export.csv` | Export BBR | `DescrizioneVariante`, `QtaResidua` |

#### Nuovo Formato V02 (1 file unificato)
| File | Descrizione | Colonne richieste |
|------|-------------|-------------------|
| `Products.csv` | Export unificato Shopify (12 colonne) | `SKU`, `Variant SKU`, `Variant Inventory Qty`, `Variant Cost`, `Variant Price`, `Tag`, `CostoBBRModels`, `Net Price`, `Trademark`, `BRAND`, `Code`, `QTY` |

### 2. Carica i file sulla webapp
1. Apri l'URL della webapp
2. Trascina o seleziona i file CSV:
   - Per il formato originale: i 3 file separati
   - Per il formato V02: solo il file `Products.csv`
3. Clicca **"Avvia Sincronizzazione"**

### 3. Scarica il risultato
1. Verifica le statistiche di elaborazione
2. Clicca **"Scarica File Aggiornamento Inventario"**
3. Importa il file CSV in Shopify

---

## 🔧 Configurazione avanzata

### Trademark filtati
La webapp filtra automaticamente i prodotti per trademark. I brand attualmente configurati sono:

```
ACME-MODELS, ALERTE, AUTOART, AVENUE43, BBR-MODELS, BURAGO, CMC, CMR,
ELIGOR, ESVAL MODEL, GP-REPLICAS, GT-SPIRIT, IXO-MODELS, KK-SCALE,
KYOSHO, LCD-MODEL, LOOKSMART, MAXIMA, MINI HELMET, MINICHAMPS, MITICA,
MITICA-DIECAST, MITICA-R, MOTORHELIX, MR-MODELS, NOREV, NZG, OTTO-MOBILE,
RIO-MODELS, SCHUCO, SOLIDO, SPARK-MODEL, STAMP-MODELS, TECNOMODEL,
TOPMARQUES, TROFEU, TRUESCALE, WERK83, DM-MODELS, UNIVERSAL HOBBIES
```

Per modificare i trademark, edita il file `logic.py`.

---

## ⚡ Funzionalità Logic V02

Il file `logic_v02.py` implementa una logica avanzata per l'elaborazione del file unificato `Products.csv` con 12 colonne.

### Logica di Elaborazione Costi

La logica distingue automaticamente tra prodotti BBR e MCWS in base alle colonne disponibili:

| Fornitore | Colonna Costo | Logica |
|-----------|---------------|--------|
| **BBR** | `CostoBBRModels` | Confronta `Variant Cost` con `CostoBBRModels` |
| **MCWS** | `Net Price` | Confronta `Variant Cost` con `Net Price` |

L'identificazione avviene controllando:
1. Se la colonna `CostoBBRModels` contiene valori → prodotto BBR
2. Altrimenti se la colonna `Net Price` contiene valori → prodotto MCWS
3. In base al tag `BBR` o `MCWS` nella colonna `Tag`

### Logica di Calcolo Prezzi

| Fornitore | Moltiplicatore | Fonte |
|-----------|----------------|-------|
| **BBR** | Fisso: **1.75** | Moltiplicatore hardcoded |
| **MCWS** | Dinamico | Letto da `Vroomi_Markup.txt` per trademark |

Per MCWS, il prezzo viene calcolato come:
```
Variant Price = (Net Price × Trademark Markup) + 0.01
```

### Filtro Variazioni

Il file di output generato da `logic_v02.py` contiene **solo** le righe con variazioni effettive di:

- **Quantità** (`QTY` diverso da `Variant Inventory Qty`)
- **Costo** (`CostoBBRModels`/`Net Price` diverso da `Variant Cost`)

Le righe con sole variazioni di prezzo o senza alcuna variazione vengono automaticamente escluse dal file di output.

### Change Log (Debug)

`logic_v02.py` include una funzione di **Change Log** per tracciare le variazioni rilevate:

| Colonna | Descrizione |
|---------|-------------|
| `Change Log` | Stringa dettagliata con tutte le modifiche applicate |

Esempi di voci nel Change Log:
- `QTY: 10→15, COST BBR: 62.35→65.00`
- `QTY: 5→5 (no change), COST MCWS: 45.00→47.50`

Per abilitare/disabilitare il Change Log, modifica la costante `ENABLE_CHANGE_LOG` in `logic_v02.py`.

### Output File

Il file di output segue la convenzione di naming:
```
{prefix}_Products.csv
```
Dove `{prefix}` è definito dalla costante `OUTPUT_PREFIX` (default: `INVENTORY_UPDATE`)

---

## 📁 Struttura del progetto

```
inventory-sync-webapp/
├── app.py              # Interfaccia Streamlit
├── logic.py            # Logica di elaborazione (versione originale)
├── logic_v02.py        # Logica di elaborazione (nuova versione avanzata)
├── Vroomi_Markup.txt   # Tabella markup per prezzi dinamici MCWS
├── requirements.txt    # Dipendenze Python
└── README.md           # Questo file
```

---

## 🛠️ Sviluppo locale

Per testare la webapp sul tuo computer:

```bash
# Clona il repository
git clone https://github.com/tuo-username/inventory-sync-webapp.git
cd inventory-sync-webapp

# Crea un ambiente virtuale
python -m venv venv
source venv/bin/activate  # Linux/Mac
# oppure
venv\Scripts\activate  # Windows

# Installa le dipendenze
pip install -r requirements.txt

# Avvia la webapp
streamlit run app.py
```

---

## 📝 Note

- I file caricati vengono elaborati solo in memoria e non vengono salvati sul server
- La webapp è accessibile da qualsiasi dispositivo connesso a internet
- Non sono richiesti database o configurazioni server

---

## 📄 Licenza

Questo progetto è distribuito senza licenza specifica. Usalo liberamente per i tuoi scopi commerciali.
