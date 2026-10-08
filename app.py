"""
app.py — Pannello di Controllo Vroomi (locale).

Pagina iniziale "Cosa vuoi fare?" con due attività principali:
  • Aggiorna l'inventario          (pannello/inventario_ui.py)
  • Crea prodotti dalle newsletter (pannello/newsletter_ui.py)
e, sotto, Catalogo fornitori automatico (pannello/catalogo_ui.py) e Impostazioni.
In cima a ogni pagina l'avviso degli aggiornamenti del programma (pannello/aggiornamenti_ui.py).
Su Streamlit Cloud (Linux), PER ORA, si apre la pagina di prima ("Sync inventario", con la
sua logica di calcolo congelata in inventario_precedente/) finché non sistemiamo la nuova.

Avvio:  streamlit run app.py   (o doppio click su "AVVIA PANNELLO.command")
"""

import platform
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # trova "pannello" da qualsiasi cartella

# TEMPORANEO: online (non sul Mac) torna l'interfaccia di prima con le regole di prima.
# Per tornare alla nuova basta togliere questo blocco.
if platform.system() != "Darwin":
    sys.path.insert(0, str(ROOT / "inventario_precedente"))
    from pagina import render as render_precedente
    render_precedente()
    st.stop()

from pannello.ui_common import apply_style, current_page
from pannello.home_ui import render_home
from pannello.inventario_ui import render_inventario
from pannello.newsletter_ui import render_newsletter
from pannello.catalogo_ui import render_catalogo
from pannello.impostazioni_ui import render_impostazioni
from pannello.aggiornamenti_ui import update_banner

st.set_page_config(
    page_title="Vroomi",
    page_icon=str(Path(__file__).parent / "pannello" / "icon.png"),
    layout="wide",
    initial_sidebar_state="collapsed",
)
apply_style()
update_banner()   # «È disponibile un aggiornamento» (controllo una volta al giorno)

{
    "home": render_home,
    "inventario": render_inventario,
    "newsletter": render_newsletter,
    "catalogo": render_catalogo,
    "impostazioni": render_impostazioni,
}[current_page()]()
