"""
pipeline.py
Orchestratore del sync automatico:
  1. scraper/carmodel_scraper.py   → scraper/carmodel_scraped.csv
  2. downloader/mcws_downloader.py → downloader/mcws_inventory.csv
  3. merger/product_merger.py      → merger/merged_products.csv
"""

import csv
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
STEPS = [
    ("Scraper carmodel.com",  [sys.executable, str(ROOT / "scraper/carmodel_scraper.py")]),
    ("Downloader MCWS",       [sys.executable, str(ROOT / "downloader/mcws_downloader.py")]),
    ("Merger",                [sys.executable, str(ROOT / "merger/product_merger.py")]),
]


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.reader(f)) - 1  # escludi header


def run_step(name: str, cmd: list[str]) -> bool:
    log(f"▶ {name}")
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=False, text=True)
    elapsed = time.time() - t0
    if result.returncode != 0:
        log(f"✗ {name} fallito (exit {result.returncode}) in {elapsed:.1f}s")
        return False
    log(f"✓ {name} completato in {elapsed:.1f}s")
    return True


def main() -> int:
    log("=" * 60)
    log("PIPELINE AUTO-SYNC — avvio")
    log("=" * 60)
    t_start = time.time()

    for name, cmd in STEPS:
        ok = run_step(name, cmd)
        if not ok:
            log(f"PIPELINE INTERROTTA allo step: {name}")
            return 1

    # Report finale
    carmodel_rows = count_csv_rows(ROOT / "scraper/carmodel_scraped.csv")
    mcws_rows     = count_csv_rows(ROOT / "downloader/mcws_inventory.csv")
    merged_rows   = count_csv_rows(ROOT / "merger/merged_products.csv")
    skipped       = carmodel_rows - merged_rows
    match_rate    = merged_rows / carmodel_rows * 100 if carmodel_rows else 0

    log("=" * 60)
    log("REPORT FINALE")
    log(f"  Righe scrappate (carmodel) : {carmodel_rows}")
    log(f"  Righe MCWS                 : {mcws_rows}")
    log(f"  Match (merged)             : {merged_rows}")
    log(f"  Skip (no match)            : {skipped}")
    log(f"  Match rate                 : {match_rate:.1f}%")
    log(f"  Durata totale              : {time.time() - t_start:.0f}s")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
