"""
pagina.py — la pagina online di prima (versione cloud del vecchio app.py, commit 7c00836^):
titolo, barra laterale "Versione cloud" e "Sync inventario" con la logica di questa cartella.
La usano sia app.py qui accanto sia l'app.py principale quando gira su Streamlit Cloud.
"""

from pathlib import Path

import streamlit as st

from sync_ui import render_sync_tab


def render():
    st.set_page_config(
        page_title="Vroomi — Pannello di Controllo",
        page_icon=str(Path(__file__).resolve().parent.parent / "pannello" / "icon.png"),
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        '<div style="font-size:2.2rem;font-weight:bold;color:#1E88E5;margin-bottom:.3rem;">'
        '📦 Vroomi — Pannello di Controllo</div>',
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.info("☁️ Versione **cloud**")
        st.caption("Qui è disponibile solo il Sync inventario. La pipeline "
                   "Catalogo → Shopify gira solo in locale sul Mac.")

    st.info("☁️ **Versione cloud** — qui trovi il **Sync inventario**. "
            "Per il catalogo carmodel → Shopify usa l'app in locale sul Mac "
            "(doppio click su *AVVIA PANNELLO.command*).")
    render_sync_tab()
