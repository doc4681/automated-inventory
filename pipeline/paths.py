"""
paths.py — tutti i percorsi del progetto in un unico posto.
Derivati dalla posizione di questo file: funziona su qualsiasi Mac, in qualsiasi cartella.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = ROOT / "config"
TRADEMARKS_FILE = CONFIG_DIR / "Valid_Trademarks.txt"
MARKUP_FILE = CONFIG_DIR / "Vroomi_Markup.txt"

DATA_DIR = ROOT / "dati"
CARMODEL_DIR = DATA_DIR / "carmodel"     # carmodel_scraped_<ts>.csv
MCWS_DIR = DATA_DIR / "mcws"             # mcws_inventory_<ts>.csv
MERGED_DIR = DATA_DIR / "merged"         # merged_products_<ts>.csv (storico)
REJECTED_DIR = DATA_DIR / "scartati"     # file di run fallite/sospette

RESULT_DIR = ROOT / "RISULTATO"
RESULT_LATEST = RESULT_DIR / "merged_products_LATEST.csv"

LOG_DIR = ROOT / "logs"


def run_timestamp() -> str:
    """Timestamp della run corrente (impostato da run.sh), altrimenti 'adesso'."""
    return os.environ.get("RUN_TIMESTAMP") or datetime.now().strftime("%Y-%m-%d_%H%M")


def output_file(directory: Path, prefix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{prefix}_{run_timestamp()}.csv"


def latest_file(directory: Path, prefix: str) -> Path | None:
    cands = sorted(directory.glob(f"{prefix}_*.csv"), key=lambda f: f.stat().st_mtime)
    return cands[-1] if cands else None
