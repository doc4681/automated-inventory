"""
product_merger.py
Join tra carmodel_scraped_{ts}.csv (scraper) e mcws_inventory_{ts}.csv (downloader).
Match: codice_produttore (carmodel) == Code (MCWS), normalizzati uppercase senza spazi.

Legge RUN_TIMESTAMP da os.environ (settato da aggiorna_inventario.command).
Fallback: usa il file più recente nella cartella output/ corrispondente.

Output: merger/output/merged_products_{ts}.csv
"""

import csv
import os
from datetime import datetime
from pathlib import Path


def resolve_input(output_dir: Path, prefix: str, ts: str) -> Path:
    """Restituisce il file con timestamp esatto, o il più recente se non trovato."""
    exact = output_dir / f"{prefix}_{ts}.csv"
    if exact.exists():
        return exact
    # Fallback: file più recente con quel prefisso
    candidates = sorted(output_dir.glob(f"{prefix}_*.csv"), key=lambda f: f.stat().st_mtime)
    if candidates:
        return candidates[-1]
    raise FileNotFoundError(f"Nessun file {prefix}_*.csv in {output_dir}")


def get_paths() -> tuple[Path, Path, Path]:
    ts = os.environ.get("RUN_TIMESTAMP", datetime.now().strftime("%Y-%m-%d_%H%M"))
    root = Path(__file__).parent.parent
    carmodel_file = resolve_input(root / "scraper" / "output", "carmodel_scraped", ts)
    mcws_file     = resolve_input(root / "downloader" / "output", "mcws_inventory", ts)
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    output_file = out_dir / f"merged_products_{ts}.csv"
    return carmodel_file, mcws_file, output_file

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
