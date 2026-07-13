"""
app.py — Pannello di Controllo Vroomi (locale).
Un'unica schermata:
  • in alto la pipeline Catalogo carmodel → Shopify (scraper/downloader/merger/enricher + scheduling)
  • in basso, a scomparsa, il vecchio strumento Sync inventario (upload CSV → download)
Avvio:  streamlit run app.py   (o doppio click su "AVVIA PANNELLO.command")
"""

import streamlit as st

import controller as ctl
from pipeline_ui import render_pipeline_tab
from sync_ui import render_sync_tab

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
    st.caption("Gira in locale su questo Mac. Le credenziali stanno in ~/.env.vroomi.")

# ── Schermata unica ──────────────────────────────────────────────────────────
# 1) Sezione principale: la pipeline Catalogo → Shopify
render_pipeline_tab()

# 2) Strumento secondario a scomparsa: il vecchio sync CSV
st.divider()
with st.expander("🔄 Altro strumento: Sync inventario da CSV (upload → download)", expanded=False):
    render_sync_tab()
