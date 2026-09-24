"""
product_merger.py
Join tra carmodel_scraped_{ts}.csv (scraper) e mcws_inventory_{ts}.csv (downloader).
Match: codice_produttore (carmodel) == Code (MCWS), normalizzati uppercase senza spazi.

Legge RUN_TIMESTAMP da os.environ (impostato da pipeline/run.sh).
Fallback: usa il file più recente in dati/carmodel/ e dati/mcws/.

Output: dati/merged/merged_products_{ts}.csv
"""

import csv
from pathlib import Path

from paths import CARMODEL_DIR, MCWS_DIR, MERGED_DIR, latest_file, output_file, run_timestamp


def resolve_input(directory: Path, prefix: str) -> Path:
    """Il file della run corrente (stesso timestamp) o, se manca, il più recente."""
    exact = directory / f"{prefix}_{run_timestamp()}.csv"
    if exact.exists():
        return exact
    latest = latest_file(directory, prefix)
    if latest:
        return latest
    raise FileNotFoundError(f"Nessun file {prefix}_*.csv in {directory}")


def get_paths() -> tuple[Path, Path, Path]:
    carmodel_file = resolve_input(CARMODEL_DIR, "carmodel_scraped")
    mcws_file = resolve_input(MCWS_DIR, "mcws_inventory")
    return carmodel_file, mcws_file, output_file(MERGED_DIR, "merged_products")


OUTPUT_FIELDS = [
    "codice_produttore",
    "our_code_mcws",
    "trademark",
    "brand_auto",
    "scala",
    "titolo",
    "prezzo_carmodel",
    "net_price_mcws",
    "colore",
    "materiale",
    "note",
    "ean",
    "url_prodotto",
    "immagini_url",
]


def normalize(s: str) -> str:
    return s.upper().replace(" ", "")


# Se la nota di carmodel contiene questa frase, la cella nota viene lasciata VUOTA.
EXCLUDE_NOTE_PHRASE = "EXCLUSIVE CARMODEL"


def clean_note(note: str) -> str:
    note = note or ""
    return "" if EXCLUDE_NOTE_PHRASE in note.upper() else note


def load_mcws(path: Path) -> dict[str, dict]:
    """Carica MCWS indicizzato per Code normalizzato."""
    index = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = normalize(row["Code"])
            index[key] = row
    return index


def main():
    carmodel_file, mcws_file, output_file = get_paths()
    print(f"Input carmodel : {carmodel_file.name}")
    print(f"Input MCWS     : {mcws_file.name}")

    mcws_index = load_mcws(mcws_file)
    total_mcws = len(mcws_index)

    matched = []
    total_carmodel = 0
    skipped = 0

    with open(carmodel_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_carmodel += 1
            key = normalize(row["codice_produttore"])
            mcws_row = mcws_index.get(key)
            if mcws_row is None:
                skipped += 1
                continue
            matched.append({
                "codice_produttore": row["codice_produttore"],
                "our_code_mcws":     mcws_row["Our Code"],
                "trademark":         row["trademark"],
                "brand_auto":        row["brand_auto"],
                "scala":             row["scala"],
                "titolo":            row["titolo"],
                "prezzo_carmodel":   row["prezzo"],
                "net_price_mcws":    mcws_row["Net Price"],
                "colore":            row["colore"],
                "materiale":         row["materiale"],
                "note":              clean_note(row["note"]),
                "ean":               mcws_row["EAN"],
                "url_prodotto":      row["url_prodotto"],
                "immagini_url":      row["immagini_url"],
            })

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(matched)

    match_rate = len(matched) / total_carmodel * 100 if total_carmodel else 0

    print(f"Totale righe carmodel : {total_carmodel}")
    print(f"Totale righe MCWS     : {total_mcws}")
    print(f"Match trovati         : {len(matched)}")
    print(f"Skip (no match)       : {skipped}")
    print(f"Match rate            : {match_rate:.1f}%")
    print(f"\nSalvato: {output_file}")


if __name__ == "__main__":
    main()
