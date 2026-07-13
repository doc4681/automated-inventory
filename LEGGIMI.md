# 📦 Vroomi — Catalogo carmodel + MCWS

> Guida rapida. In 1 minuto sai cosa lanciare e dove trovare il risultato.

## 🖥️ Modo più semplice: il Pannello di Controllo

**Doppio click su  `AVVIA PANNELLO.command`** → si apre nel browser un pannello con i pulsanti.
Al primo avvio prepara da solo l'ambiente (1-2 min). Da lì puoi:
- lanciare la pipeline completa e vedere il **log in diretta**;
- scaricare l'ultimo risultato;
- accendere/spegnere l'**arricchimento Shopify** (note → `custom.notes`);
- attivare/sospendere la **pianificazione automatica** (ogni 2 giorni), senza toccare il Terminale.

Ha anche una seconda scheda con la vecchia webapp di **sync inventario** (upload→download).

> 🆕 **Nuovo Mac (collaboratore):** copia la cartella, crea `~/.env.vroomi` con le credenziali
> (vedi sotto), assicurati di avere Chrome e Python 3, poi doppio click su `AVVIA PANNELLO.command`.
> Tutto il resto (ambiente, dipendenze, pianificazione per quella macchina) lo fa il pannello da sé.

---

## ▶️ In alternativa: aggiornare il catalogo da riga di comando

**Doppio click su  `AGGIORNA INVENTARIO.command`**

Fa tutto da solo, in 3 passi:
1. 🔍 Scarica i dati dei prodotti da **carmodel.com** (solo i marchi in `Valid_Trademarks.txt`, immagini incluse)
2. ⬇️ Scarica il listino inventario da **MCWS** (login automatico)
3. 🔗 Unisce i due: tiene solo i prodotti il cui `codice_produttore` esiste anche su MCWS

⏱️ Dura ~20–40 minuti. Tieni il Mac **acceso e sbloccato** durante la run.

## 📄 Dove trovo il risultato

➡️ **`RISULTATO/merged_products_LATEST.csv`**

È sempre il file più recente, pronto da importare su Shopify. (Lo storico con data resta in `merger/output/`.)

## 🔔 Se qualcosa va storto

- I **dati buoni precedenti non vengono mai sovrascritti** da una run fallita.
- Riceverai una notifica macOS con l'esito.
- I dettagli di ogni run sono in `logs/run_<data>.log`.

## ⚙️ Configurazione

| File | A cosa serve |
|------|--------------|
| `Valid_Trademarks.txt` | I marchi da scaricare (uno per riga). Aggiungi/togli righe qui. |
| `Vroomi_Markup.txt` | I ricarichi prezzo per marchio. |
| `~/.env.vroomi` | Credenziali MCWS (fuori dal repo, mai condiviso). |

## 🗂️ Cosa c'è nelle cartelle

| Cartella / file | Cos'è |
|-----------------|-------|
| `AGGIORNA INVENTARIO.command` | **👈 Il pulsante. È l'unica cosa che lanci.** |
| `RISULTATO/` | Il file finale da importare su Shopify. |
| `scraper/` `downloader/` `merger/` | Il "motore" dei 3 passi. Non serve aprirlo. |
| `shopify_enricher/` | Step 4 **opzionale**: scrive le note su Shopify (vedi sotto). |
| `run_local.sh` | La logica condivisa (usata dal pulsante e dallo scheduler). |
| `logs/` | I log automatici di ogni run. |
| `_archivio/` | Vecchi file superati. Si possono ignorare. |

---

## 🛍️ Step 4 OPZIONALE — Shopify: note → metafield `custom.notes`

Scrive il campo `note` del catalogo nel metafield **`custom.notes`** dei prodotti
**già presenti** nel tuo store Shopify. Match per **EAN→barcode** (primario) e
**codice_produttore→SKU** (fallback). I prodotti non nel catalogo non vengono toccati.
Scope: *overwrite di tutti i match* (se la nota è vuota, il metafield viene cancellato).

**È DISATTIVATO di default.** Si attiva/disattiva con una variabile.

### Credenziali Shopify (metodo nuovo, post-2026)
Da gennaio 2026 Shopify non usa più i token `shpat_` da copiare a mano: si usa
un'app della **Dev Dashboard** e lo script ottiene il token da solo (client
credentials grant) usando **Client ID + Client Secret**.

App già creata: **`Vroomi Enricher_Claude`**. Le credenziali sono in:
**dev.shopify.com → app → Settings → Credentials**
- **Client ID** (identificatore, non segreto)
- **Client Secret** (`shpss_...`)

Queste sono già state messe in `~/.env.vroomi`:
```bash
export SHOPIFY_STORE_DOMAIN="scn8p4-h7.myshopify.com"
export SHOPIFY_CLIENT_ID="...."
export SHOPIFY_CLIENT_SECRET="shpss_...."
export ENABLE_SHOPIFY=1      # 1 = attivo, 0 (o assente) = disattivo
```
L'app deve avere gli scope **read_products** e **write_products** (già a posto).

### Come usarlo
- **Provalo senza scrivere** (dry-run, mostra cosa farebbe):
  ```bash
  python3 shopify_enricher/shopify_enricher.py
  ```
- **Scrivi davvero su Shopify**:
  ```bash
  python3 shopify_enricher/shopify_enricher.py --apply
  ```
- **Solo primi 50 prodotti (test)**: aggiungi `--limit 50`
- Quando `ENABLE_SHOPIFY=1`, lo step parte **automaticamente** anche dal pulsante
  `AGGIORNA INVENTARIO.command` (come 4° passo, dopo il merge).
- Per **disattivarlo**: metti `ENABLE_SHOPIFY=0` (o togli la riga) in `~/.env.vroomi`.

---

## ⏰ Esecuzione automatica (attualmente SOSPESA)

C'era una pianificazione ogni 2 giorni alle 07:00. **È stata sospesa** — ora lanci tutto a mano.

⚠️ Nota: il solo `bootout` NON basta — al riavvio del Mac launchd ricarica il job.
Per sospenderla **davvero** (persistente) serve anche `disable`.

Per **sospenderla** in modo permanente:
```bash
launchctl bootout gui/$(id -u)/com.vroomi.inventory
launchctl disable gui/$(id -u)/com.vroomi.inventory
```
Per **riattivarla** in futuro (serve `enable`, perché ora è disabilitata):
```bash
launchctl enable gui/$(id -u)/com.vroomi.inventory
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.vroomi.inventory.plist
```

---

## ⚠️ Strumento SEPARATO: la webapp Streamlit

I file **`app.py`**, **`logic.py`**, **`logic_v02.py`**, **`logic_v03.py`**, **`icon.png`** **NON** fanno parte di questo catalogo. Sono una **webapp Streamlit a parte** per sincronizzare le **quantità/costi** di magazzino (Shopify ↔ MCWS/BBR), un lavoro diverso. Si lancia con `streamlit run app.py`. Lasciata qui apposta, ma è un altro strumento.
