"""
catalog.py — anagrafica brand: trademark validi, markup per brand, calcolo prezzo.

File sorgente:
  Valid_Trademarks.txt   un brand per riga (stile UPPER/hyphen, es. OTTO-MOBILE)
  Vroomi_Markup.txt       'Brand<TAB o spazi>Markup%'  (es. 'Otto Mobile\t1,50')
Dentro automated-inventory vale la copia unica in ../config/ (la stessa usata da
pipeline e pannello). Le copie in questa cartella servono solo quando la cartella
gira da sola (zip per Giuliano).

Matching brand robusto: si normalizza a chiave "compatta" (solo alfanumerici,
maiuscolo), cosi' 'OTTO-MOBILE' == 'Otto Mobile' e 'TOPMARQUES' == 'Top Marques'.
"""

from __future__ import annotations

import os
import re
import math
from pathlib import Path


# ── individuazione file ──────────────────────────────────────────────────────
def _find_file(name: str) -> Path:
    candidates = []
    env = os.environ.get(f"MCW_{name.upper().replace('.TXT','').replace('.','_')}")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).parent
    candidates += [
        here.parent / "config" / name,                        # dentro automated-inventory
        here / name,                                          # cartella da sola (zip)
        Path.home() / "automated-inventory" / "config" / name,
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"{name} non trovato. Cercato in: " + ", ".join(str(c) for c in candidates)
    )


# ── normalizzazione brand ────────────────────────────────────────────────────
def compact_key(name: str) -> str:
    """Chiave di confronto: solo lettere/cifre, maiuscolo. 'Otto-Mobile' -> 'OTTOMOBILE'."""
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


# alias manuali per differenze non riconducibili alla sola normalizzazione
# (es. plurale 'MODEL' vs 'MODELS'). chiave = compact del brand newsletter,
# valore = compact del brand nel file markup.
MARKUP_ALIASES = {
    "ESVALMODEL": "ESVALMODELS",
    "MITICADIECAST": "MITICA",
    "MITICAR": "MITICA",
}


# ── caricamento ──────────────────────────────────────────────────────────────
def load_trademarks() -> dict[str, str]:
    """Ritorna {compact_key: nome_originale} dei trademark validi."""
    path = _find_file("Valid_Trademarks.txt")
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name = re.sub(r"^\d+\s+", "", line.strip())
        if name:
            out.setdefault(compact_key(name), name)
    return out


def load_markup() -> dict[str, tuple[float, str]]:
    """Ritorna {compact_key: (moltiplicatore, nome_originale)}. Salta l'header.
    Il nome originale serve come `vendor` Shopify (in maiuscolo)."""
    path = _find_file("Vroomi_Markup.txt")
    out: dict[str, tuple[float, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("trademark"):
            continue
        # divide sull'ultimo blocco numerico (il markup) e prende il resto come nome
        m = re.match(r"^(.*?)[\t ]+([\d]+[.,][\d]+)\s*$", line)
        if not m:
            continue
        name, mk = m.group(1).strip(), m.group(2).replace(",", ".")
        try:
            out[compact_key(name)] = (float(mk), name)
        except ValueError:
            continue
    return out


# ── API pubblica ─────────────────────────────────────────────────────────────
class Catalog:
    def __init__(self) -> None:
        self.trademarks = load_trademarks()   # compact -> nome
        self.markup = load_markup()           # compact -> (float, nome)

    def is_valid(self, brand: str) -> bool:
        return compact_key(brand) in self.trademarks

    def canonical(self, brand: str) -> str:
        return self.trademarks.get(compact_key(brand), brand)

    def _markup_entry(self, brand: str) -> tuple[float, str] | None:
        key = compact_key(brand)
        if key in self.markup:
            return self.markup[key]
        alias = MARKUP_ALIASES.get(key)
        if alias and alias in self.markup:
            return self.markup[alias]
        return None

    def markup_for(self, brand: str) -> float | None:
        e = self._markup_entry(brand)
        return e[0] if e else None

    def vendor_for(self, brand: str) -> str:
        """Nome vendor Shopify: nome dal file markup in MAIUSCOLO (coerente con
        i prodotti Vroomi esistenti, es. 'SPARK MODEL'), altrimenti il trademark."""
        e = self._markup_entry(brand)
        return (e[1].upper() if e else self.canonical(brand).upper())


# ── prezzo ───────────────────────────────────────────────────────────────────
def round_90(value: float) -> float:
    """Arrotonda per eccesso al successivo X.90 (convenzione prezzi Vroomi).
    219.15 -> 219.90 ; 219.90 -> 219.90 ; 219.95 -> 220.90."""
    euros = math.floor(value)
    candidate = euros + 0.90
    if candidate + 1e-9 >= value:
        return round(candidate, 2)
    return round(euros + 1 + 0.90, 2)


# Stesse soglie del pannello (pannello/logic_v03.py): i modelli economici hanno
# un ricarico più alto. Così il prezzo non cambia al primo "Adeguamento Markup".
COST_THRESHOLD_LOW, MARKUP_LOW = 10.0, 2.2
COST_THRESHOLD_MID, MARKUP_MID = 20.0, 1.9


def effective_markup(cost: float, brand_markup: float) -> float:
    if cost < COST_THRESHOLD_LOW:
        return MARKUP_LOW
    if cost < COST_THRESHOLD_MID:
        return MARKUP_MID
    return brand_markup


def compute_price(cost: float, markup: float, style: str = "90") -> float:
    raw = cost * effective_markup(cost, markup)
    if style == "90":
        return round_90(raw)
    return round(raw, 2)
