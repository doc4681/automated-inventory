"""
app.py — Pannello di Controllo Vroomi (locale).
Due schede (entrambe sempre visibili):
  • Catalogo carmodel → Shopify  (pipeline: scraper/downloader/merger/enricher + scheduling)
  • Sync inventario              (webapp upload CSV → download, con export Excel)
Avvio:  streamlit run app.py   (o doppio click su "AVVIA PANNELLO.command")
"""

import platform

import streamlit as st

import controller as ctl
from pipeline_ui import render_pipeline_tab
from sync_ui import render_sync_tab

# La pipeline (scraper/downloader/scheduling) gira SOLO in locale sul Mac.
# Su Streamlit Cloud (Linux) mostriamo solo il Sync inventario, che invece funziona.
IS_LOCAL_MAC = platform.system() == "Darwin"

st.set_page_config(
    page_title="Vroomi — Pannello di Controllo",
    page_icon="icon.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    '<div style="font-size:2.2rem;font-weight:bold;color:#1E88E5;margin-bottom:.3rem;">'
    '📦 Vroomi — Pannello di Controllo</div>',
    unsafe_allow_html=True,
)

# ── Sidebar: stato a colpo d'occhio ──────────────────────────────────────────
with st.sidebar:
    st.header("Stato")
    if IS_LOCAL_MAC:
        creds = ctl.credentials_status()
        st.write(f"**Credenziali MCWS:** {'✅' if creds['mcws'] else '❌'}")
        st.write(f"**Credenziali Shopify:** {'✅' if creds['shopify'] else '❌'}")
        st.write(f"**Arricchimento Shopify:** {'🟢 ON' if creds['enable_shopify'] else '⚪️ OFF'}")
        sched = ctl.schedule_status()
        sched_badge = {'attivo': '🟢 Attivo', 'sospeso': '🟠 Sospeso', 'assente': '⚪️ Non installato'}[sched]
        st.write(f"**Pianificazione:** {sched_badge}")
        st.write(f"**Pipeline:** {'🔵 in esecuzione' if ctl.is_running() else '⚪️ ferma'}")
        res = ctl.latest_result()
        if res:
            st.write(f"**Ultimo merge:** {res['rows']} righe")
            st.caption(f"{res['name']} · {res['mtime']}")
        st.divider()
        st.caption("Gira in locale su questo Mac. Credenziali in ~/.env.vroomi o credenziali.env.")
    else:
        st.info("☁️ Versione **cloud**")
        st.caption("Qui è disponibile solo il Sync inventario. La pipeline "
                   "Catalogo → Shopify gira solo in locale sul Mac.")

# ── Contenuto: locale = due schede; cloud = solo Sync ────────────────────────
if IS_LOCAL_MAC:
    tab1, tab2 = st.tabs(["🚗 Catalogo → Shopify", "🔄 Sync inventario"])
    with tab1:
        render_pipeline_tab()
    with tab2:
        render_sync_tab()
else:
    st.info("☁️ **Versione cloud** — qui trovi il **Sync inventario**. "
            "Per il catalogo carmodel → Shopify usa l'app in locale sul Mac "
            "(doppio click su *AVVIA PANNELLO.command*).")
    render_sync_tab()
