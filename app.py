"""
app.py — Pannello di Controllo Vroomi (locale).

Pagina iniziale "Cosa vuoi fare?" con due attività principali:
  • Aggiorna l'inventario          (pannello/inventario_ui.py)
  • Crea prodotti dalle newsletter (pannello/newsletter_ui.py)
e, sotto, Catalogo fornitori automatico (pannello/catalogo_ui.py) e Impostazioni.
Su Streamlit Cloud (Linux) resta disponibile solo "Aggiorna l'inventario".

Avvio:  streamlit run app.py   (o doppio click su "AVVIA PANNELLO.command")
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))  # trova "pannello" da qualsiasi cartella

from pannello.ui_common import apply_style, current_page
from pannello.home_ui import render_home
from pannello.inventario_ui import render_inventario
from pannello.newsletter_ui import render_newsletter
from pannello.catalogo_ui import render_catalogo
from pannello.impostazioni_ui import render_impostazioni

st.set_page_config(
    page_title="Vroomi",
    page_icon=str(Path(__file__).parent / "pannello" / "icon.png"),
    layout="wide",
    initial_sidebar_state="collapsed",
)
apply_style()

{
    "home": render_home,
    "inventario": render_inventario,
    "newsletter": render_newsletter,
    "catalogo": render_catalogo,
    "impostazioni": render_impostazioni,
}[current_page()]()
