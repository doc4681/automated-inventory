"""
product_merger.py
Join tra carmodel_scraped.csv (scraper) e mcws_inventory.csv (downloader).
Match: codice_produttore (carmodel) == Code (MCWS), normalizzati uppercase senza spazi.

Output: merger/merged_products.csv
"""

import csv
from pathlib import Path

CARMODEL_FILE = Path(__file__).parent.parent / "scraper" / "carmodel_scraped.csv"
MCWS_FILE = Path(__file__).parent.parent / "downloader" / "mcws_inventory.csv"
OUTPUT_FILE = Path(__file__).parent / "merged_products.csv"

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
    mcws_index = load_mcws(MCWS_FILE)
    total_mcws = len(mcws_index)

    matched = []
    total_carmodel = 0
    skipped = 0

    with open(CARMODEL_FILE, newline="", encoding="utf-8") as f:
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
                "note":              row["note"],
                "ean":               mcws_row["EAN"],
                "url_prodotto":      row["url_prodotto"],
                "immagini_url":      row["immagini_url"],
            })

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(matched)

    match_rate = len(matched) / total_carmodel * 100 if total_carmodel else 0

    print(f"Totale righe carmodel : {total_carmodel}")
    print(f"Totale righe MCWS     : {total_mcws}")
    print(f"Match trovati         : {len(matched)}")
    print(f"Skip (no match)       : {skipped}")
    print(f"Match rate            : {match_rate:.1f}%")
    print(f"\nSalvato: {OUTPUT_FILE}")

    if matched:
        print("\nPrime 3 righe:")
        print(",".join(OUTPUT_FIELDS))
        for row in matched[:3]:
            print(",".join(str(row[k]) for k in OUTPUT_FIELDS))


if __name__ == "__main__":
    main()
