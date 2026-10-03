# 📦 Vroomi — Catalogo carmodel + MCWS (automatico)

**Cosa fa:** scarica i prodotti da **carmodel.com** (solo i marchi in `config/Valid_Trademarks.txt`,
immagini incluse), scarica il listino **MCWS**, li unisce e produce il file per Shopify.
**Gira da solo** ogni 2 giorni alle 07:00.

## 📄 Il risultato

➡️ **`RISULTATO/merged_products_LATEST.csv`** — sempre l'ultimo, pronto da importare su Shopify.

A ogni run ricevi una **notifica macOS** (✅ aggiornato / ⚠️ fallito).
Se una run fallisce, il risultato precedente **non viene toccato**.

## ▶️ Come si usa

| Voglio… | Faccio… |
|---|---|
| Non fare niente | Niente: la pianificazione automatica è attiva (ogni 2 giorni, 07:00). |
| Aggiornare adesso | Doppio click su **`AGGIORNA INVENTARIO.command`** (~25 min, lascia il Mac acceso). |
| Installare o aggiornare tutto da GitHub | Una riga nel Terminale (vedi **Installazione e aggiornamento**). |
| Usare il pannello | Doppio click su **`AVVIA PANNELLO.command`** → si apre nel browser (vedi sotto). |
| Aggiornare disponibilità, costi e prezzi su Shopify | Pannello → **📦 Aggiorna l'inventario**. |
| Mettere su Shopify i prodotti di una newsletter MCWS | Pannello → **🆕 Crea prodotti dalle newsletter** (vedi sotto). |
| Vedere lo stato del catalogo, accendere/spegnere l'automatico | Pannello → **🔁 Catalogo fornitori**. |

### 🖥️ Il pannello

Si apre su **"Cosa vuoi fare?"** con due scelte principali; ogni pagina è guidata a passi numerati.

| Pagina | A cosa serve |
|---|---|
| 📦 **Aggiorna l'inventario** | **In automatico** (serve la chiave Shopify): niente file da caricare, legge i prodotti da Shopify, usa il listino MCWS scaricato (o ne scarica uno nuovo), premi **Controlla** e poi **Applica su Shopify**. Oppure **con i file**, come prima: carichi l'export e scarichi il file da importare. |
| 🆕 **Crea prodotti dalle newsletter** | Scrivi il numero della newsletter (o scegli tutte le recenti), premi **Controlla** (non crea niente) e poi **Crea le bozze su Shopify**. Mostra l'elenco dei prodotti creati / da creare. |
| 🔁 **Catalogo fornitori** | L'ultimo catalogo carmodel + MCWS da scaricare, **Aggiorna adesso** con l'avanzamento passo per passo, l'interruttore dell'aggiornamento automatico. |
| ⚙️ **Impostazioni** | Password MCWS e chiave Shopify (si scrivono lì, finiscono in `credenziali.env`), pulsanti per modificare marchi e ricarichi. |

Durante la run si apre una finestra di Chrome: è normale (serve a superare Cloudflare), **non chiuderla**.

## 🗂️ Cosa c'è nella cartella

| Cartella / file | Cos'è | Serve toccarlo? |
|---|---|---|
| `AGGIORNA INVENTARIO.command` | Pulsante: aggiorna adesso | ✅ lo usi |
| `AVVIA PANNELLO.command` | Pulsante: apre il pannello di controllo | ✅ lo usi |
| `RISULTATO/` | Il file finale per Shopify | ✅ lo prendi da qui |
| `config/` | `Valid_Trademarks.txt` (marchi da scaricare, uno per riga) e `Vroomi_Markup.txt` (ricarichi) | ✏️ solo se cambi marchi/ricarichi |
| `credenziali.env` | Login MCWS e Shopify (mai condividerlo) | ✏️ solo se cambiano le password |
| `logs/` | Un log per ogni run (`run_<data>.log`) | 🔍 solo se qualcosa va storto |
| `dati/` | File intermedi e storico (ultimi 15 per tipo, pulizia automatica) | ❌ |
| `pipeline/` | Il motore: scraper, downloader, merge, Shopify, `run.sh` | ❌ |
| `pannello/` | Il codice del pannello (una pagina per file: `home_ui`, `inventario_ui` + `inventario_auto_ui`, `newsletter_ui`, `catalogo_ui`, `impostazioni_ui`) e `inventario_sync.py` (inventario automatico) | ❌ |
| `app.py`, `.streamlit/`, `requirements.txt`, `.venv/` | Avvio e aspetto del pannello, dipendenze Python | ❌ |
| `Vroomi-Newsletter/` | Newsletter MCWS → bozze Shopify (vedi sotto): usato dal pannello e da Giuliano | ✅ |
| `_archivio/` | Roba vecchia, non usata. Si può cancellare. | ❌ |

## ⚙️ Come funziona (i 4 passi di `pipeline/run.sh`)

1. **carmodel.com** → `dati/carmodel/` — scartato se troppo piccolo o se mancano >10% dei marchi
2. **MCWS** (login automatico) → `dati/mcws/` — scartato se troppo piccolo o calo >50% vs run precedente
3. **Merge**: tiene i prodotti il cui `codice_produttore` esiste anche su MCWS → `dati/merged/` + `RISULTATO/merged_products_LATEST.csv`
4. **Shopify** (opzionale, spento di default): scrive le note nel metafield `custom.notes`

I file scartati finiscono in `dati/scartati/`. Una sola run alla volta: se ne parte una seconda, esce subito.

## ⏰ Esecuzione automatica

Si attiva/sospende dal **pannello** (🔁 Catalogo fornitori → "Aggiorna da solo"). È un job di macOS
(`launchd`, `~/Library/LaunchAgents/com.vroomi.inventory.plist`): parte ogni 2 giorni alle 07:00.
Se a quell'ora il Mac dorme, parte appena si risveglia; se è spento, salta a quella successiva.

## 📰 Newsletter MCWS → nuovi prodotti Shopify

Un solo programma: la cartella **`Vroomi-Newsletter/`**. Legge le newsletter di
modelcarswholesale.com (colonna **"Recent Newsletters"**, es. *24-09-2026 - BURAGO*), tiene
solo i marchi in `Valid_Trademarks.txt` **con un ricarico** in `Vroomi_Markup.txt`, e crea
su Shopify in **BOZZA** i prodotti che non ci sono ancora. Funziona su Mac **Intel e Apple Silicon**.

Due modi di usarlo, stesso programma:
- **Pannello** → 🆕 **Crea prodotti dalle newsletter**: scrivi il numero della newsletter (es. `15538`,
  il numero nel suo link) o scegli tutte le recenti, premi **🔍 Controlla** (non crea niente) e poi
  **✅ Crea le bozze su Shopify**.
- **Script con doppio click** dentro `Vroomi-Newsletter/` (quelli che usa Giuliano):
  `1 - PROVA`, `2 - CREA SCHEDE DRAFT` (tutte), `3 - CREA UNA NEWSLETTER` (per ID).
  Istruzioni in `Vroomi-Newsletter/LEGGIMI.txt`.

La scheda creata è come quelle già in negozio: titolo `MARCA AUTO - DESCRIZIONE`, SKU = codice
produttore, barcode = ID MCWS, costo = prezzo netto, prezzo = costo × ricarico (sotto 10 € ×2,2,
sotto 20 € ×1,9) arrotondato a ,90, foto grande, materiale e note dalla scheda MCWS, campi
`custom.*` (per i modelli da corsa anche evento, pilota e sottocategoria). I prodotti già presenti
(stesso SKU o barcode) vengono saltati: rilanciare è sicuro.

⚠️ Un marchio **senza ricarico** in `config/Vroomi_Markup.txt` viene saltato (es. MR-MODELS):
aggiungi la riga del ricarico e rilancia.

Dentro questo progetto usa `config/` e `credenziali.env` della cartella principale. Per dare lo
strumento a Giuliano basta zippare **solo** la cartella `Vroomi-Newsletter/`, senza `.venv/` e `output/` (ha le sue
copie di marchi/ricarichi; `credenziali.env` va compilato sul suo Mac partendo da `credenziali.esempio.env`).

## 🛍️ Shopify (opzionale): note → metafield `custom.notes`

Aggiunge la nota del catalogo ai prodotti **già presenti** nello store che non ce l'hanno.
Match per EAN→barcode, poi codice_produttore→SKU. Non sovrascrive e non cancella mai note esistenti.

- Si accende dal pannello (🔁 Catalogo fornitori → Opzioni avanzate → "Scrivi anche le note") oppure con `ENABLE_SHOPIFY=1` in `credenziali.env`.
- Credenziali: app **`Vroomi Enricher_Claude`** della Dev Dashboard Shopify
  (dev.shopify.com → app → Settings → Credentials): `SHOPIFY_CLIENT_ID` + `SHOPIFY_CLIENT_SECRET`, scope `read_products`/`write_products`. Lo strumento Newsletter (quantità 1 sulle schede nuove) richiede anche `read_locations`, `read_inventory`, `write_inventory`.
- Prova senza scrivere nulla: `.venv/bin/python pipeline/shopify_enricher.py` (aggiungi `--apply` per scrivere davvero, `--limit 50` per provare su pochi).

## 🆕 Installazione e aggiornamento (da GitHub, senza blocchi di macOS)

Serve **Google Chrome** e **Python 3.10 o più recente** (https://www.python.org/downloads/).

1. Apri il **Terminale** (⌘ + barra spaziatrice → `Terminale` → Invio).
2. Incolla questa riga e premi Invio:

   ```
   curl -fsSL https://raw.githubusercontent.com/doc4681/automated-inventory/main/installa.sh | bash
   ```

3. Si crea (o si aggiorna) la cartella **`Vroomi`** nella tua Inizio e **si apre da solo il pannello**.
   Le volte dopo: doppio click su `AVVIA PANNELLO.command` dentro quella cartella.
4. Nel pannello: ⚙️ **Impostazioni** → password MCWS e chiave Shopify (se trova un `credenziali.env`
   in una copia vecchia lo riusa da solo). Chi usa l'aggiornamento automatico: 🔁 **Catalogo
   fornitori** → accendi "Aggiorna da solo" (se puntava alla cartella vecchia, il pannello lo dice
   e lo sposta con un click).

**Per aggiornare** rilancia la stessa riga: vengono sostituiti solo i file del programma; password,
`dati/`, `RISULTATO/`, `logs/` e l'ambiente Python restano. Per usare un'altra cartella:
`… | bash -s -- "$HOME/Desktop/Vroomi"`.

Perché niente blocchi: macOS mette in "quarantena" solo i file scaricati da browser, Drive, WhatsApp o
mail; quelli scaricati dal Terminale si aprono subito. Se hai comunque una copia scaricata a mano e
macOS dice *"è danneggiato"* o *"sviluppatore non identificato"*: Terminale → `xattr -cr ` (con lo
spazio), trascina dentro la cartella, Invio.

## 🔔 Se qualcosa va storto

Il pannello (🔁 Catalogo fornitori) mostra i problemi dell'ultimo aggiornamento; il registro completo è
in `logs/run_<data>.log` (righe con ✗).

| Nel log vedi… | Causa / soluzione |
|---|---|
| `Bad CPU type in executable` | Risolto (set 2026): il chromedriver ora viene preso per l'architettura giusta del Mac. Se ricompare, cancella `~/Library/Application Support/vroomi/chromedriver/`. |
| `Impossibile avviare Chrome` | Chrome non installato o appena aggiornato senza rete: riprova. |
| `Cloudflare non superato` | Il sito ha bloccato la sessione: di solito alla run successiva passa. |
| `login rifiutato da MCWS` | Password MCWS cambiata: aggiornala in `credenziali.env`. |
| `copertura brand … mancanti: …` | Un marchio di `Valid_Trademarks.txt` non esiste più su carmodel: toglilo dal file. |

## 📦 "Aggiorna l'inventario" (pannello)

Due modi, stessa logica di calcolo (`pannello/logic_v03.py`: disponibilità, costi, prezzi con i
ricarichi, tag SALE, PRE-ORDER mai toccati).

**⚡ In automatico** (sul Mac, serve la chiave Shopify) — come per le newsletter, niente file:

| Prima (3 file) | Adesso |
|---|---|
| Export prodotti da Shopify | Letto **direttamente da Shopify** |
| Listino MCWS | L'ultimo scaricato dal catalogo automatico, oppure **«Scaricane uno nuovo adesso»** (2-3 min, si apre Chrome) |
| Giacenze BBR | Lo carichi **una volta**: il pannello lo ricorda (`dati/bbr/`) e ti avvisa se ha più di 3 giorni |
| Importare il file su Shopify | **«Applica su Shopify»**: scrive quantità, costo, prezzo, prezzo barrato e tag SALE |

1. Premi **🔍 Controlla**: non cambia niente, mostra quanti prodotti tornano disponibili / diventano
   esauriti / cambiano prezzo, con l'elenco (scaricabile in Excel).
2. Se va bene premi **✅ Applica queste N modifiche su Shopify** (usa gli stessi listini del controllo).

Protezioni: un listino MCWS scaricato con meno di 1000 righe (o meno della metà del precedente) viene
scartato; se più del 30% dei prodotti disponibili diventerebbe esaurito **non applica niente**
finché non spunti «applica lo stesso». Rilanciare è sicuro: riscrive solo quello che è ancora diverso.
La quantità va nella sede di magazzino principale (o `SHOPIFY_LOCATION_ID` in `credenziali.env`).
Scope dell'app Shopify: `read_products`, `write_products`, `read_inventory`, `write_inventory`,
`read_locations` (gli stessi dello strumento newsletter). Report in `dati/inventario/`, log in
`logs/inventario_<data>.log`. Da Terminale: `.venv/bin/python -m pannello.inventario_sync`
(controllo) e `--apply` (applica); opzioni `--solo-prezzi`, `--mcws-nuovo`, `--senza-bbr`.

**📄 Con i file**, come prima (anche su Streamlit Cloud, `app.py`): carichi i CSV (Shopify + listino
MCWS/BBR) e scarichi il file di aggiornamento. Logica in `pannello/logic.py` (formato originale) e
`pannello/logic_v03.py` (formato Products.csv + markup).

### ⏪ Versione precedente (temporanea, link Streamlit separato)

Finché non sistemiamo la nuova funzione, la pagina **"Sync inventario"** com'era prima della nuova
interfaccia è disponibile come app separata: cartella `inventario_precedente/` (con la sua copia
congelata di `logic.py` e `logic_v03.py`; marchi e ricarichi restano quelli di `config/`).

- **Streamlit Cloud**: *Create app* → stesso repository, **Main file path**
  `inventario_precedente/app.py` → nuovo link, separato da quello del pannello.
- **In locale**: `.venv/bin/streamlit run inventario_precedente/app.py`

Quando la nuova funzione è a posto: si cancella l'app su Streamlit Cloud e la cartella
`inventario_precedente/`.
