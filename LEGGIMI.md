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
| Vedere lo stato, il log, accendere/spegnere l'automatico | Doppio click su **`AVVIA PANNELLO.command`** → si apre nel browser. |
| Mettere su Shopify i prodotti di una newsletter MCWS | Pannello → sezione **📰 Newsletter** (vedi sotto). |

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
| `pannello/` | Il codice del pannello (e della scheda "Sync inventario") | ❌ |
| `app.py`, `requirements.txt`, `.venv/` | Avvio pannello e dipendenze Python | ❌ |
| `Vroomi-Newsletter/` | Newsletter MCWS → bozze Shopify (vedi sotto): usato dal pannello e da Giuliano | ✅ |
| `_archivio/` | Roba vecchia, non usata. Si può cancellare. | ❌ |

## ⚙️ Come funziona (i 4 passi di `pipeline/run.sh`)

1. **carmodel.com** → `dati/carmodel/` — scartato se troppo piccolo o se mancano >10% dei marchi
2. **MCWS** (login automatico) → `dati/mcws/` — scartato se troppo piccolo o calo >50% vs run precedente
3. **Merge**: tiene i prodotti il cui `codice_produttore` esiste anche su MCWS → `dati/merged/` + `RISULTATO/merged_products_LATEST.csv`
4. **Shopify** (opzionale, spento di default): scrive le note nel metafield `custom.notes`

I file scartati finiscono in `dati/scartati/`. Una sola run alla volta: se ne parte una seconda, esce subito.

## ⏰ Esecuzione automatica

Si attiva/sospende dal **pannello** (sezione "Esecuzione automatica"). È un job di macOS
(`launchd`, `~/Library/LaunchAgents/com.vroomi.inventory.plist`): parte ogni 2 giorni alle 07:00.
Se a quell'ora il Mac dorme, parte appena si risveglia; se è spento, salta a quella successiva.

## 📰 Newsletter MCWS → nuovi prodotti Shopify

Un solo programma: la cartella **`Vroomi-Newsletter/`**. Legge le newsletter di
modelcarswholesale.com (colonna **"Recent Newsletters"**, es. *24-09-2026 - BURAGO*), tiene
solo i marchi in `Valid_Trademarks.txt` **con un ricarico** in `Vroomi_Markup.txt`, e crea
su Shopify in **BOZZA** i prodotti che non ci sono ancora. Funziona su Mac **Intel e Apple Silicon**.

Due modi di usarlo, stesso programma:
- **Pannello** → sezione 📰: scrivi l'ID della newsletter (es. `15538`, il numero nel suo link;
  vuoto = tutte), premi **🔍 Prova** (non scrive nulla) e poi **🛍️ Crea su Shopify in BOZZA**.
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

- Si accende dal pannello (interruttore "Arricchimento Shopify") oppure con `ENABLE_SHOPIFY=1` in `credenziali.env`.
- Credenziali: app **`Vroomi Enricher_Claude`** della Dev Dashboard Shopify
  (dev.shopify.com → app → Settings → Credentials): `SHOPIFY_CLIENT_ID` + `SHOPIFY_CLIENT_SECRET`, scope `read_products`/`write_products`.
- Prova senza scrivere nulla: `.venv/bin/python pipeline/shopify_enricher.py` (aggiungi `--apply` per scrivere davvero, `--limit 50` per provare su pochi).

## 🆕 Installazione su un altro Mac

1. Copia la cartella (senza `credenziali.env`, `.venv/`, `dati/`, `logs/`).
2. Serve **Google Chrome** e **Python 3** (`brew install python`).
3. Rinomina `credenziali.esempio.env` → `credenziali.env` e compila `MCWS_USERNAME` / `MCWS_PASSWORD`
   (tra virgolette **singole**).
4. Doppio click su `AVVIA PANNELLO.command`: al primo avvio prepara tutto da solo (1-2 min).
   Poi dal pannello attiva l'esecuzione automatica.

Se macOS dice che il file *"è danneggiato"* o *"sviluppatore non identificato"*: apri il Terminale,
scrivi `xattr -cr ` (con lo spazio), trascina dentro la cartella del progetto, premi Invio.

## 🔔 Se qualcosa va storto

Apri l'ultimo `logs/run_<data>.log` (o il pannello, che lo mostra) e cerca le righe con ✗.

| Nel log vedi… | Causa / soluzione |
|---|---|
| `Bad CPU type in executable` | Risolto (set 2026): il chromedriver ora viene preso per l'architettura giusta del Mac. Se ricompare, cancella `~/Library/Application Support/vroomi/chromedriver/`. |
| `Impossibile avviare Chrome` | Chrome non installato o appena aggiornato senza rete: riprova. |
| `Cloudflare non superato` | Il sito ha bloccato la sessione: di solito alla run successiva passa. |
| `login rifiutato da MCWS` | Password MCWS cambiata: aggiornala in `credenziali.env`. |
| `copertura brand … mancanti: …` | Un marchio di `Valid_Trademarks.txt` non esiste più su carmodel: toglilo dal file. |

## 🔄 Scheda "Sync inventario" del pannello

Strumento **separato** dal catalogo: carichi i CSV (Shopify + listino MCWS/BBR) e scarichi il file
di aggiornamento quantità/costi/prezzi. Logica in `pannello/logic.py` (formato originale) e
`pannello/logic_v03.py` (formato Products.csv + markup). Funziona anche su Streamlit Cloud (`app.py`).
