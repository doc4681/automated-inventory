"""
catalog.py — anagrafica brand: trademark validi, markup per brand, calcolo prezzo.

File sorgente:
  Valid_Trademarks.txt   un brand per riga (stile UPPER/hyphen, es. OTTO-MOBILE)
  Vroomi_Markup.txt       'Brand<TAB o spazi>Markup%'  (es. 'Otto Mobile\t1,50')
                          + righe 'COSTO SOTTO <euro>  <markup>' = ricarico fisso
                          per i modelli economici (es. 'COSTO SOTTO 50\t2,30')
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


_TIER_RE = re.compile(r"^COSTO\s+SOTTO\s+(\d+(?:[.,]\d+)?)\s*(?:€|EUR|EURO)?$", re.I)


def _markup_lines(path: Path):
    """(nome, markup) per ogni riga 'Nome<TAB o spazi>1,50' del file markup."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.lower().startswith("trademark"):
            continue
        # divide sull'ultimo blocco numerico (il markup) e prende il resto come nome
        m = re.match(r"^(.*?)[\t ]+([\d]+[.,][\d]+)\s*$", line)
        if not m:
            continue
        try:
            yield m.group(1).strip(), float(m.group(2).replace(",", "."))
        except ValueError:
            continue


def load_markup() -> dict[str, tuple[float, str]]:
    """Ritorna {compact_key: (moltiplicatore, nome_originale)} dei brand. Salta
    l'header e le righe 'COSTO SOTTO ...' (vedi load_cost_tiers). Il nome
    originale serve come `vendor` Shopify (in maiuscolo)."""
    out: dict[str, tuple[float, str]] = {}
    for name, mk in _markup_lines(_find_file("Vroomi_Markup.txt")):
        if not _TIER_RE.match(name):
            out[compact_key(name)] = (mk, name)
    return out


def load_cost_tiers() -> list[tuple[float, float]]:
    """Fasce di costo dal file markup: righe 'COSTO SOTTO 50<TAB>2,30' significano
    "se il costo MCWS è sotto 50 €, ricarico 2,30 (al posto di quello del brand)".
    Ritorna [(soglia, markup)] ordinate per soglia crescente. Se il file non ne
    ha, valgono le fasce storiche DEFAULT_COST_TIERS."""
    tiers = []
    for name, mk in _markup_lines(_find_file("Vroomi_Markup.txt")):
        m = _TIER_RE.match(name)
        if m:
            tiers.append((float(m.group(1).replace(",", ".")), mk))
    return sorted(tiers) or list(DEFAULT_COST_TIERS)


# ── API pubblica ─────────────────────────────────────────────────────────────
class Catalog:
    def __init__(self) -> None:
        self.trademarks = load_trademarks()   # compact -> nome
        self.markup = load_markup()           # compact -> (float, nome)
        self.cost_tiers = load_cost_tiers()   # [(soglia €, markup)]

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


# Fasce usate solo se Vroomi_Markup.txt non ha righe 'COSTO SOTTO ...'
# (le stesse del pannello, pannello/logic_v03.py).
DEFAULT_COST_TIERS = ((10.0, 2.2), (20.0, 1.9))


def effective_markup(cost: float, brand_markup: float,
                     tiers=DEFAULT_COST_TIERS) -> float:
    """Ricarico da applicare: quello della prima fascia di costo in cui il costo
    rientra (es. sotto 50 € -> 2,30), altrimenti quello del brand."""
    for threshold, mk in tiers:
        if cost < threshold:
            return mk
    return brand_markup


def compute_price(cost: float, markup: float, style: str = "90",
                  tiers=DEFAULT_COST_TIERS) -> float:
    raw = cost * effective_markup(cost, markup, tiers)
    if style == "90":
        return round_90(raw)
    return round(raw, 2)
