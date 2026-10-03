"""
inventario_precedente/app.py — "Aggiorna inventario" nella VERSIONE PRECEDENTE (temporanea).

È la pagina "Sync inventario" com'era prima della nuova interfaccia, da pubblicare come
app Streamlit separata (link a parte) finché non sistemiamo la nuova funzione.
Usa la sua copia della logica di calcolo (logic.py, logic_v03.py in questa cartella),
ma legge marchi e ricarichi dai file condivisi in config/.

Su Streamlit Cloud: "Main file path" = inventario_precedente/app.py
In locale:          streamlit run inventario_precedente/app.py

Quando la nuova funzione è sistemata: si cancella l'app su Streamlit Cloud e questa cartella.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))  # logic/logic_v03/sync_ui di questa cartella

from sync_ui import render_sync_tab

st.set_page_config(
    page_title="Vroomi — Inventario (versione precedente)",
    page_icon=str(Path(__file__).resolve().parent.parent / "pannello" / "icon.png"),
    layout="wide",
)

st.markdown("## 📦 Vroomi — Aggiorna inventario (versione precedente)")
st.caption("Versione temporanea: è la pagina di prima, in attesa che la nuova sia sistemata.")

render_sync_tab()
